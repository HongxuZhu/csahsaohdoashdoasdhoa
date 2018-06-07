import FDDC_PART2.preprocessing.htmlParser as parser
import FDDC_PART2.preprocessing.autoTagging as tagger
import re

# 公告id,增发对象,发行方式,增发数量,增发金额,锁定期,认购方式
dz_trainpath = '/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/定增/dingzeng.train'
dz_htmlpath = '/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/定增/html/'

# 公告id,甲方,乙方,项目名称,合同名称,合同金额上限,合同金额下限,联合体成员
ht_trainpath = '/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/hetong.train'
ht_htmlpath = '/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/html/'

ht_train = open('/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/ht.train', 'a+')
ht_test = open('/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/ht.test', 'a+')
ht_dev = open('/home/utopia/corpus/FDDC_part2_data/round1_train_20180518/重大合同/ht.dev', 'a+')


def makeTrainFile(trainpath, htmlpath, train, test, dev):
    c = 0
    with open(trainpath, 'r') as file:
        for line in file:
            line = line.encode('utf-8').decode('utf-8-sig')
            line = line[0:len(line) - 1]
            entity = line.split('\t')
            id = entity[0]
            c += 1
            mod = int(id) % 6
            if mod < 4:
                tagger.tag_text(htmlpath + id + '.html', line, train)
            if mod == 4:
                tagger.tag_text(htmlpath + id + '.html', line, test)
            if mod == 5:
                tagger.tag_text(htmlpath + id + '.html', line, dev)


def find_allheaders_fromhtml(trainpath, htmlpath, index):
    dict = {}
    with open(trainpath, 'r') as file:
        id = None
        for line in file:
            entity = line.split('\t')
            length = len(entity)
            if length > index:
                if entity[0] != id:
                    id = entity[0]
                    val = entity[index]
                    find_header_fromhtml(htmlpath, id, val, dict)
    print('----------------- over -----------------')
    print(sorted(dict.items(), key=lambda d: d[1], reverse=True))


# 20503293 建信基金管理有限责任公司
def find_header_fromhtml(htmlpath, id, val, dict):
    html = htmlpath + id + '.html'
    head = parser.show_header(html, val)
    print(id, val, head)
    if isinstance(head, str):
        head = re.sub('\s+', '', head)
        c = dict.get(head)
        if c is None:
            dict[head] = 1
        else:
            dict[head] = c + 1
        pass


# find_allheaders_fromhtml(ht_trainpath, ht_htmlpath, 1)
makeTrainFile(ht_trainpath, ht_htmlpath, ht_train, ht_test, ht_dev)
