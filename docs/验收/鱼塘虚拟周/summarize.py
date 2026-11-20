"""把测试目录的独立世界结果合成逐种子表与每群报表；同一批鱼才可比较。"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def summarize(source, destination):
    hashes={}
    destination.mkdir(parents=True,exist_ok=True)
    with (destination/"策略分种子.csv").open("w",encoding="utf-8-sig",newline="") as f, (
            destination/"群周报对账.csv").open("w",encoding="utf-8-sig",newline="") as g:
        finance=csv.writer(f)
        weekly=csv.writer(g)
        finance.writerow(["饲料除数","满阶恢复费","种子","策略","玩家类型","玩家周数","有效竿","落袋",
                          "售出条数","售鱼到账","饲料支出","装备支出","期末库存条数","期末库存估值",
                          "现金净增","含库存净收益","积分获得","饵料积分支出","新展品","抛竿结果SHA256"])
        weekly.writerow(["饲料除数","满阶恢复费","种子","策略","群","存塘人数","活跃钓手","次日主动养鱼",
                         "完整次日样本","鱼币净新增","点亮人数","活跃钓手"])
        for folder,divisor,repair in (("log",16,80),("feed12",12,80),("repair-only",16,120),("repair120",12,120)):
            for seed in (17,31,53,79,101,137):
                for mode in ("sell","natural","feed","select"):
                    world=json.loads((source/folder/f"{divisor}-{seed}-{mode}.json").read_text())
                    fish_hash=world["fish_hash"]
                    assert hashes.setdefault(seed,fish_hash)==fish_hash
                    for member in ("brief","split","expert"):
                        total=Counter()
                        for group in ("lake","bay"):
                            total.update(world["players"][group+"/"+member])
                        fields=("casts","landed","sold","sales","feed","repairs","stock_n","stock",
                                "cash","net","points_earned","points_spent","lit")
                        finance.writerow([divisor,repair,seed,mode,member,2,*[total[k] for k in fields],fish_hash])
                    for group,r in sorted(world["reports"].items()):
                        weekly.writerow([divisor,repair,seed,mode,group,*r["活跃钓手中主动存塘"],*r["首次存塘次日主动养鱼"],
                                         r["鱼币净新增"],*r["活跃钓手中点亮新鱼种"]])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    summarize(args.source,args.destination)
