# encoding=utf8
import itertools
import os
import pickle
import re
from collections import OrderedDict

import numpy as np
import tensorflow as tf
from data_utils import load_word2vec, input_from_line, BatchManager
from loader import augment_with_pretrained, prepare_dataset
from loader import char_mapping, tag_mapping
from loader import load_sentences, update_tag_scheme
from model import Model
from utils import get_logger, make_path, create_model, save_model
from utils import print_config, save_config, load_config, test_ner

from FDDC_PART2.preprocessing.htmlParser import levelText_withtable

flags = tf.app.flags
flags.DEFINE_boolean("clean", False, "clean train folder")
flags.DEFINE_boolean("train", False, "Whether train the model")
# configurations for the model
flags.DEFINE_integer("seg_dim", 20, "Embedding size for segmentation, 0 if not used")
flags.DEFINE_integer("char_dim", 100, "Embedding size for characters")
flags.DEFINE_integer("lstm_dim", 100, "Num of hidden units in LSTM, or num of filters in IDCNN")
flags.DEFINE_string("tag_schema", "iobes", "tagging schema iobes or iob")

# configurations for training
flags.DEFINE_float("clip", 5, "Gradient clip")
flags.DEFINE_float("dropout", 0.5, "Dropout rate")
flags.DEFINE_integer("batch_size", 100, "batch size")
flags.DEFINE_float("lr", 0.001, "Initial learning rate")
flags.DEFINE_string("optimizer", "adam", "Optimizer for training")
flags.DEFINE_boolean("pre_emb", True, "Wither use pre-trained embedding")
flags.DEFINE_boolean("zeros", False, "Wither replace digits with zero")
flags.DEFINE_boolean("lower", True, "Wither lower case")

flags.DEFINE_integer("max_epoch", 100, "maximum training epochs")
flags.DEFINE_integer("steps_check", 100, "steps per checkpoint")
flags.DEFINE_string("ckpt_path", "ckpt", "Path to save model")
flags.DEFINE_string("summary_path", "summary", "Path to store summaries")
flags.DEFINE_string("log_file", "train.log", "File for log")
flags.DEFINE_string("map_file", "maps.pkl", "file for maps")
flags.DEFINE_string("vocab_file", "vocab.json", "File for vocab")
flags.DEFINE_string("config_file", "config_file", "File for config")
flags.DEFINE_string("script", "conlleval", "evaluation script")
flags.DEFINE_string("result_path", "result", "Path for results")
flags.DEFINE_string("emb_file", os.path.join("data", "vec.txt"), "Path for pre_trained embedding")
flags.DEFINE_string("train_file", os.path.join("data", "ht.train"), "Path for train data")
flags.DEFINE_string("dev_file", os.path.join("data", "ht.dev"), "Path for dev data")
flags.DEFINE_string("test_file", os.path.join("data", "ht.test"), "Path for test data")

flags.DEFINE_string("model_type", "idcnn", "Model type, can be idcnn or bilstm")
# flags.DEFINE_string("model_type", "bilstm", "Model type, can be idcnn or bilstm")

FLAGS = tf.app.flags.FLAGS
assert FLAGS.clip < 5.1, "gradient clip should't be too much"
assert 0 <= FLAGS.dropout < 1, "dropout rate between 0 and 1"
assert FLAGS.lr > 0, "learning rate must larger than zero"
assert FLAGS.optimizer in ["adam", "sgd", "adagrad"]

import os

# 解决项目路径问题
os.chdir('/home/utopia/PycharmProjects/csahsaohdoashdoasdhoa/FDDC_PART2/expand/NER_IDCNN_CRF')


# config for the model
def config_model(char_to_id, tag_to_id):
    config = OrderedDict()
    config["model_type"] = FLAGS.model_type
    config["num_chars"] = len(char_to_id)
    config["char_dim"] = FLAGS.char_dim
    config["num_tags"] = len(tag_to_id)
    config["seg_dim"] = FLAGS.seg_dim
    config["lstm_dim"] = FLAGS.lstm_dim
    config["batch_size"] = FLAGS.batch_size

    config["emb_file"] = FLAGS.emb_file
    config["clip"] = FLAGS.clip
    config["dropout_keep"] = 1.0 - FLAGS.dropout
    config["optimizer"] = FLAGS.optimizer
    config["lr"] = FLAGS.lr
    config["tag_schema"] = FLAGS.tag_schema
    config["pre_emb"] = FLAGS.pre_emb
    config["zeros"] = FLAGS.zeros
    config["lower"] = FLAGS.lower
    return config


def evaluate(sess, model, name, data, id_to_tag, logger):
    logger.info("evaluate:{}".format(name))
    ner_results = model.evaluate(sess, data, id_to_tag)
    eval_lines = test_ner(ner_results, FLAGS.result_path)
    for line in eval_lines:
        logger.info(line)
    f1 = float(eval_lines[1].strip().split()[-1])

    if name == "dev":
        best_test_f1 = model.best_dev_f1.eval()
        if f1 > best_test_f1:
            tf.assign(model.best_dev_f1, f1).eval()
            logger.info("new best dev f1 score:{:>.3f}".format(f1))
        return f1 > best_test_f1
    elif name == "test":
        best_test_f1 = model.best_test_f1.eval()
        if f1 > best_test_f1:
            tf.assign(model.best_test_f1, f1).eval()
            logger.info("new best test f1 score:{:>.3f}".format(f1))
        return f1 > best_test_f1


def train():
    # load data sets
    train_sentences = load_sentences(FLAGS.train_file, FLAGS.lower, FLAGS.zeros)
    dev_sentences = load_sentences(FLAGS.dev_file, FLAGS.lower, FLAGS.zeros)
    test_sentences = load_sentences(FLAGS.test_file, FLAGS.lower, FLAGS.zeros)

    # Use selected tagging scheme (IOB / IOBES)
    update_tag_scheme(train_sentences, FLAGS.tag_schema)
    update_tag_scheme(test_sentences, FLAGS.tag_schema)

    # create maps if not exist
    if not os.path.isfile(FLAGS.map_file):
        # create dictionary for word
        if FLAGS.pre_emb:
            dico_chars_train = char_mapping(train_sentences, FLAGS.lower)[0]
            dico_chars, char_to_id, id_to_char = augment_with_pretrained(
                dico_chars_train.copy(),
                FLAGS.emb_file,
                list(itertools.chain.from_iterable(
                    [[w[0] for w in s] for s in test_sentences])
                )
            )
        else:
            _c, char_to_id, id_to_char = char_mapping(train_sentences, FLAGS.lower)

        # Create a dictionary and a mapping for tags
        _t, tag_to_id, id_to_tag = tag_mapping(train_sentences)
        with open(FLAGS.map_file, "wb") as f:
            pickle.dump([char_to_id, id_to_char, tag_to_id, id_to_tag], f)
    else:
        with open(FLAGS.map_file, "rb") as f:
            char_to_id, id_to_char, tag_to_id, id_to_tag = pickle.load(f)

    # prepare data, get a collection of list containing index
    train_data = prepare_dataset(
        train_sentences, char_to_id, tag_to_id, FLAGS.lower
    )
    dev_data = prepare_dataset(
        dev_sentences, char_to_id, tag_to_id, FLAGS.lower
    )
    test_data = prepare_dataset(
        test_sentences, char_to_id, tag_to_id, FLAGS.lower
    )
    print("%i / %i / %i sentences in train / dev / test." % (
        len(train_data), len(dev_data), len(test_data)))

    train_manager = BatchManager(train_data, FLAGS.batch_size)
    dev_manager = BatchManager(dev_data, 100)
    test_manager = BatchManager(test_data, 100)
    # make path for store log and model if not exist
    make_path(FLAGS)
    if os.path.isfile(FLAGS.config_file):
        config = load_config(FLAGS.config_file)
    else:
        config = config_model(char_to_id, tag_to_id)
        save_config(config, FLAGS.config_file)
    make_path(FLAGS)

    log_path = os.path.join("log", FLAGS.log_file)
    logger = get_logger(log_path)
    print_config(config, logger)

    # limit GPU memory
    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True
    steps_per_epoch = train_manager.len_data
    with tf.Session(config=tf_config) as sess:
        model = create_model(sess, Model, FLAGS.ckpt_path, load_word2vec, config, id_to_char, logger)
        logger.info("start training")
        loss = []
        for i in range(100):
            for batch in train_manager.iter_batch(shuffle=True):
                step, batch_loss = model.run_step(sess, True, batch)
                loss.append(batch_loss)
                if step % FLAGS.steps_check == 0:
                    iteration = step // steps_per_epoch + 1
                    logger.info("iteration:{} step:{}/{}, "
                                "NER loss:{:>9.6f}".format(
                        iteration, step % steps_per_epoch, steps_per_epoch, np.mean(loss)))
                    loss = []

            best = evaluate(sess, model, "dev", dev_manager, id_to_tag, logger)
            if best:
                save_model(sess, model, FLAGS.ckpt_path, logger)
            # evaluate(sess, model, "test", test_manager, id_to_tag, logger)


def evaluate_line_ht(htmlpath):
    config = load_config(FLAGS.config_file)
    logger = get_logger(FLAGS.log_file)
    # limit GPU memory
    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True
    with open(FLAGS.map_file, "rb") as f:
        char_to_id, id_to_char, tag_to_id, id_to_tag = pickle.load(f)
    with tf.Session(config=tf_config) as sess:
        model = create_model(sess, Model, FLAGS.ckpt_path, load_word2vec, config, id_to_char, logger)
        print(htmlpath)
        s_arr = levelText_withtable(htmlpath)
        for j in range(len(s_arr)):
            sen = s_arr[j]
            result = model.evaluate_line(sess, input_from_line(sen, char_to_id), id_to_tag)
            entities = result.get('entities')
            if len(entities) > 0:
                for en in entities:
                    en['sid'] = j
                    print(en)
        print('-------------------------------------------------')


def evaluate_ht():
    submit_path_ht = 'submit_sample/hetong.csv'
    submit_path_file = open(submit_path_ht, 'a+', encoding='gbk')
    submit_path_file.write('公告id,甲方,乙方,项目名称,合同名称,合同金额上限,合同金额下限,联合体成员\n')
    config = load_config(FLAGS.config_file)
    logger = get_logger(FLAGS.log_file)
    # limit GPU memory
    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True
    with open(FLAGS.map_file, "rb") as f:
        char_to_id, id_to_char, tag_to_id, id_to_tag = pickle.load(f)
    with tf.Session(config=tf_config) as sess:
        model = create_model(sess, Model, FLAGS.ckpt_path, load_word2vec, config, id_to_char, logger)
        rootdir = '/home/utopia/corpus/FDDC_part2_data/FDDC_announcements_round1_test_a_20180605/重大合同/html/'
        list = os.listdir(rootdir)  # 列出文件夹下所有的目录与文件
        for i in range(0, len(list)):
            htmlpath = os.path.join(rootdir, list[i])
            if os.path.isfile(htmlpath):
                print(htmlpath)
                s_arr = levelText_withtable(htmlpath)
                candidates = []
                for j in range(len(s_arr)):
                    sen = s_arr[j]
                    result = model.evaluate_line(sess, input_from_line(sen, char_to_id), id_to_tag)
                    entities = result.get('entities')
                    if len(entities) > 0:
                        for en in entities:
                            en['sid'] = j
                            en['pid'] = list[i]
                            candidates.append(en)
                org_ht(candidates, submit_path_file)
                print('-------------------------------------------------')


'''
def org_ht(candidates, submit_path_file):
    # pid,YF,JY为联合主键，YF不为空
    types = {'JF': [], 'YF': [], 'XM': [], 'HT': [], 'AU': [], 'AD': [], 'LH': []}
    if len(candidates) > 0:
        pid = candidates[0]['pid']
        for can in candidates:
            type = can.get('type')
            types[type].append(can)
        jfs = types['JF']
        yfs = types['YF']
        xms = types['XM']
        hts = types['HT']
        aus = types['AU']
        ads = types['AD']
        lhs = types['LH']

        yfset = set()
        for yf in yfs:
            yfset.add(yf['word'])
        for yfword in yfset:  # 因为乙方不为空，所以先确定乙方
            # 假设乙方只出现一次，假设不成立但可以容忍
            near_jf = findNearest(jfs, yfs, yfword, False)
            near_xm = findNearest(xms, yfs, yfword, False)
            near_ht = findNearest(hts, yfs, yfword, False)
            near_au = findNearest(aus, yfs, yfword, False)
            near_ad = findNearest(ads, yfs, yfword, False)
            near_lh = findNearest(lhs, yfs, yfword, False)

            if near_au == '':
                near_au = near_ad
            if near_ad == '':
                near_ad = near_au
            tmp = 0
            if near_au < near_ad:
                tmp = near_ad
                near_ad = near_au
                near_au = tmp

            # 甲方被消费掉则清除
            jfs = filter(lambda x: x['word'] != near_jf, jfs)  # 满足条件则保留

            ht = []
            ht.append(pid)
            ht.append(near_jf)
            ht.append(yfword)
            ht.append(near_xm)
            ht.append(near_ht)
            ht.append(near_au)
            ht.append(near_ad)
            ht.append(near_lh)
            submit_ht(ht, submit_path_file)
'''


def org_ht(candidates, submit_path_file):
    # pid,YF,JY为联合主键，YF不为空
    types = {'JF': [], 'YF': [], 'XM': [], 'HT': [], 'AU': [], 'AD': [], 'LH': []}
    if len(candidates) > 0:
        pid = candidates[0]['pid']
        for can in candidates:
            type = can.get('type')
            types[type].append(can)
        jfs = types['JF']
        yfs = types['YF']
        xms = types['XM']
        hts = types['HT']
        aus = types['AU']
        ads = types['AD']
        lhs = types['LH']

        yfset = set()
        for yf in yfs:
            yfset.add(yf['word'])

        pair_jf = findNearestPair(jfs, yfs)
        pair_xm = findNearestPair(xms, yfs)
        pair_ht = findNearestPair(hts, yfs)
        pair_au = findNearestPair(aus, yfs)
        pair_ad = findNearestPair(ads, yfs)
        pair_lh = findNearestPair(lhs, yfs)
        for yfword in yfset:  # 因为乙方不为空，所以先确定乙方
            near_jf = find_near(pair_jf, yfword)
            near_xm = find_near(pair_xm, yfword)
            near_ht = find_near(pair_ht, yfword)
            near_au = find_near(pair_au, yfword)
            near_ad = find_near(pair_ad, yfword)
            near_lh = find_near(pair_lh, yfword)

            if near_au == '':
                near_au = near_ad
            if near_ad == '':
                near_ad = near_au
            if near_au < near_ad:
                tmp = near_ad
                near_ad = near_au
                near_au = tmp

            ht = []
            ht.append(pid)
            ht.append(near_jf)
            ht.append(yfword)
            ht.append(near_xm)
            ht.append(near_ht)
            ht.append(near_au)
            ht.append(near_ad)
            ht.append(near_lh)
            submit_ht(ht, submit_path_file)


def find_near(pairs, word):
    for pair in pairs:
        if pair[1] == word:
            return pair[0]
            # return re.sub(',', '', pair[0])
    return ''


def submit_ht(ht, submit_path_file):
    pid = ht[0]
    near_jf = ht[1]
    yfword = ht[2]
    near_xm = ht[3]
    near_ht = ht[4]
    near_au = ht[5]
    near_ad = ht[6]
    near_lh = ht[7]
    print('pid={},JF={},YF={},XM={},HT={},AU={},AD={},LH={}'
          .format(pid, near_jf, yfword, near_xm, near_ht, near_au, near_ad, near_lh))

    line = ','.join(ht) + '\n'
    submit_path_file.write(line)


def findNearest(subTypesTarget, subTypesSource, source, flag):
    min_sid_distance = 100000
    min_word_distance = 100000
    target = ''
    for ss in subTypesSource:
        if ss['word'] == source:
            for st in subTypesTarget:
                if flag or st['word'] != source:  # 右半个条件特意考虑甲方和乙方不同，且乙方识别率高
                    sid_distance = abs(ss['sid'] - st['sid'])
                    if sid_distance < min_sid_distance:
                        min_sid_distance = sid_distance
                        target = st['word']
                    elif sid_distance == min_sid_distance:
                        word_distance = min(abs(ss['start'] - st['end']), abs(ss['end'] - st['start']))
                        if word_distance < min_word_distance:
                            min_word_distance = word_distance
                            target = st['word']
    return target


def findNearestPair(subTypesTarget, subTypesPK):
    list = []
    for sk in subTypesPK:
        pk = sk['word']
        if len(subTypesTarget) == 0:
            list.append(('', pk, 100000, 100000))
        else:
            for st in subTypesTarget:
                if pk != st['word']:
                    sid_distance = abs(sk['sid'] - st['sid'])
                    word_distance = min(abs(sk['start'] - st['end']), abs(sk['end'] - st['start']))
                    target = st['word']
                    list.append((target, pk, sid_distance, word_distance))
    list.sort(key=lambda x: (x[2], x[3]))

    pairs = []
    pkset = set()
    tergset = set()
    for candidate in list:
        temp_t = candidate[0]
        temp_s = candidate[1]
        if temp_s not in pkset and temp_t not in tergset:
            pkset.add(temp_s)
            tergset.add(temp_t)
            pairs.append((temp_t, temp_s))
    return pairs


def main(_):
    line = '近日，江苏中天科技股份有限公司（上证代码： 600522 ，以下简称“中天科技股份”或“公司”）及控股子公司中天科技海缆有限公司（以下简称“中天科技海缆”）分别收到中标通知书，确认中天科技股份为盛东如东海上风力发电有限责任公司“海装如东海上风电场工程（如东 H3# ）海底光电复合电缆及附件”招标项目的中标人、中天科技海缆为“国家电网公司输变电项目 2017 年（新增）变电设备（含电缆）招标采购-电力电缆及电缆附件”招标项目的中标人，现将中标情况公告如下：'
    # evaluate_line_ht('/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/html/16773644.html')
    # evaluate_line_ht('/home/utopia/corpus/FDDC_part2_data/FDDC_announcements_round1_test_a_20180605/重大合同/html/68')
    # evaluate_line_ht('/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/html/122957.html')
    evaluate_ht()


if __name__ == "__main__":
    tf.app.run(main)
