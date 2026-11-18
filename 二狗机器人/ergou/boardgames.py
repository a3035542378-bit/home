"""Additional board and deduction rules for the group game catalog."""
from itertools import combinations
from .scenarios import puzzle, replace_at, swap


puzzle("soko","推箱入库","人 箱",[0,4],"3×3 库房，无障碍。推箱到右下角格 8。人可向四邻走，箱后有空格时才可推。",
       lambda p,b:b==8,lambda p,b:soko(p,b))


def soko(p,b):
    def neighbor(i,dx,dy):
        x,y=i%3+dx,i//3+dy
        return 3*y+x if 0<=x<3 and 0<=y<3 else None
    moves={}
    for name,dx,dy in (("上",0,-1),("下",0,1),("左",-1,0),("右",1,0)):
        dest=neighbor(p,dx,dy)
        if dest is None:
            continue
        new=neighbor(b,dx,dy) if dest==b else b
        if new is not None:
            moves[name]=(dest,new)
    return moves


puzzle("reversi","夹击翻面","棋列",["XOO_OOX"],"X 在空格落子，沿两侧将被 X 夹住的连续 O 翻成 X。翻满棋列。",
       lambda s:"O" not in s,lambda s:{str(i+1):(flip(s,i),) for i,c in enumerate(s) if c=="_"})


def flip(s,i):
    line=list(s)
    line[i]="X"
    for d in (-1,1):
        j=i+d
        while 0<=j<len(line) and line[j]=="O":
            j+=d
        if 0<=j<len(line) and line[j]=="X":
            for k in range(i+d,j,d):
                line[k]="X"
    return "".join(line)


puzzle("latin","拉丁方格","方格",["1_3_3_3_2"],"3×3 方格逐空填入 1–3，每行每列无重复。输入下一空的数字，可用重置重新填格。",
       lambda s:"_" not in s,lambda s:latin(s))


def latin(s):
    if "_" not in s:
        return {}
    i=s.index("_")
    return {c:(replace_at(s,i,c),) for c in "123" if c not in s[i//3*3:i//3*3+3] and c not in s[i%3::3]}


puzzle("nonogram","数字绘格","行一 行二 行三",["","",""],"每行须放一个连续色块，长度 1、3、1；列提示同序 1、3、1。填行号及起点，如 1-2。",
       lambda *rows:all(rows) and [col.count("#") for col in zip(*rows)]==[1,3,1],
       lambda *rows:{f"{i+1}-{start+1}":tuple(("."*start+"#"*n+"."*(3-start-n)) if k==i else row for k,row in enumerate(rows))
       for i,n in enumerate((1,3,1)) for start in range(4-n)})
puzzle("ken","算笼组合","四格",["____"],"2×2 格每行每列只含 1、2。左列乘积二，上排左格小于右格。填下一格。",
       lambda s:"_" not in s,lambda s:cage_moves(s))


def cage_moves(board):
    if "_" not in board:return {}
    moves={}
    for v in "12":
        s=replace_at(board,board.index("_"),v)
        lines=(s[:2],s[2:],s[::2],s[1::2])
        if any("_" not in line and len(set(line))!=2 for line in lines):continue
        if "_" not in s[:2] and s[0]>=s[1]:continue
        if "_" not in s[::2] and int(s[0])*int(s[2])!=2:continue
        moves[v]=(s,)
    return moves
puzzle("coins","翻币配对","币面",["正反反正"],"只能翻任意两枚朝向相反的币（互换正反），把所有正面集中到左半。输入两枚序号。",
       lambda s:s=="正正反反",lambda s:{f"{a+1}{b+1}":(swap(s,a,b),) for a,b in combinations(range(4),2) if s[a]!=s[b]})
puzzle("merge","合并到八","数列",["2222"],"选一对相邻等值数合成两倍，只能从选择的位置合并。做出 8。",
       lambda s:s=="8",lambda s:{str(i+1):(s[:i]+str(2*int(s[i]))+s[i+2:],) for i in range(len(s)-1) if s[i]==s[i+1]})
puzzle("factor","因子树","叶节点",["24"],"选一个合数叶子拆成两因子。把 24 拆成全为素数的叶子。",
       lambda s:all(int(v) in (2,3) for v in s.split(",")),lambda s:{
       f"{v}={d}×{int(v)//d}":(",".join(sorted(s.split(",")[:i]+[str(d),str(int(v)//d)]+s.split(",")[i+1:],key=int)),)
       for i,v in enumerate(s.split(",")) for d in range(2,int(int(v)**0.5)+1) if int(v)%d==0})
puzzle("calc","四数算式","手数",["1,2,3,4"],"任取两个数做加、减、乘或整除，将结果放回，只剩 24 为胜。输入如 3×4。",
       lambda s:s=="24",lambda s:calc(s))


def calc(s):
    nums=list(map(int,s.split(",")))
    moves={}
    for i,x in enumerate(nums):
        for j,y in enumerate(nums):
            if i==j:
                continue
            for sign,z in (("+",x+y),("-",x-y),("×",x*y),("÷",x//y if y and x%y==0 else None)):
                if z is not None and z>=0:
                    rest=[v for k,v in enumerate(nums) if k not in (i,j)]
                    moves[f"{x}{sign}{y}"]=(",".join(map(str,sorted(rest+[z]))),)
    return moves


puzzle("nimgrid","威佐夫取子","甲 乙",[3,5],"两堆从一堆取任意数量或两堆同时取等量。给机器人留下 (1,2) 或 (2,1) 即赢得残局。",
       lambda a,b:sorted((a,b))==[1,2],lambda a,b:{**{f"甲{n}":(a-n,b) for n in range(1,a+1)},**{f"乙{n}":(a,b-n) for n in range(1,b+1)},
       **{f"双{n}":(a-n,b-n) for n in range(1,min(a,b)+1)}})
puzzle("nimble","滚珠奇偶","珠位",["024"],"三枚珠在六格轨道。每步一珠向左移，不能重叠也不能越珠。排成 012。",
       lambda s:s=="012",lambda s:{f"{c}到{j}":(replace_at(s,i,str(j)),) for i,c in enumerate(s) for j in range(int(s[i-1])+1 if i else 0,int(c))})
puzzle("ferry2","重量渡船","此岸 船岸",["123",0],"人重 1、2、3，船载重 3，每次一至两人划船。全员抵达对岸。",
       lambda s,p:not s,lambda s,p:{team:("".join(c for c in "123" if (c in s)!=(c in team)),1-p) for team in ("1","2","3","12") if all((c in s)==(p==0) for c in team)})
puzzle("dice","骰面漫步","顶 北 东 位置",[1,2,3,0],"在四格环道向东或北滚骰，每次位置前进一。起点顶1北2东3，回到起点且顶面为6。",
       lambda t,n,e,p:p==0 and t==6,lambda t,n,e,p:{"东滚":(7-e,n,t,(p+1)%4),"北滚":(7-n,t,e,(p+1)%4)})
puzzle("wires","插线配电","红端 蓝端 红灯 蓝灯",[0,0,0,0],"两线可轮换插孔 0–2。红插 2、蓝插 1 时通电会锁定两灯；同孔通电则复位。",
       lambda r,b,x,y:x==y==1,lambda r,b,x,y:{"插红":((r+1)%3,b,x,y),"插蓝":(r,(b+1)%3,x,y),
       "通电":(r,b,int(r==2 and r!=b),int(b==1 and r!=b))})
puzzle("matrix","行列轮移","矩阵",["CABFDE"],"2×3 矩阵，两行可独立循环右移，列可上下交换。拼成 ABCDEF。",
       lambda s:s=="ABCDEF",lambda s:{"推上":(s[2]+s[:2]+s[3:],),"推下":(s[:3]+s[-1]+s[3:5],),**{f"交换{i+1}":(swap(s,i,i+3),) for i in range(3)}})
puzzle("knapsack","背包远征","选件",[""],"四件装备 A/B/C/D 重 2/3/4/5，价值 3/4/6/7。承重七，凑至少十分。",
       lambda s:sum(v for c,v in zip("ABCD",(3,4,6,7)) if c in s)>=10,
       lambda s:{c:("".join(sorted(s+c)) if c not in s else s.replace(c,""),) for c in "ABCD" if c in s or sum(v for k,v in zip("ABCD",(2,3,4,5)) if k in s+c)<=7})
puzzle("mines","扫雷推演","标旗",[""],"一维格 1–5，已揭 2、4 两格均显示一，且全场只有一枚雷。标记后提交检验。",
       lambda s:s=="完成",lambda s:{"旗1":("1",),"旗3":("3",),"旗5":("5",),"提交":("完成",) if s=="3" else ("",)})
puzzle("circuit","布尔电路","开关甲 开关乙 输出锁",[0,0,0],"先让异或门为真锁存，再让与门为真触发输出。",
       lambda a,b,s:s==2,lambda a,b,s:{"翻甲":(1-a,b,s),"翻乙":(a,1-b,s),"锁存":(a,b,1) if a!=b else None,"触发":(a,b,2) if a and b and s==1 else None})
puzzle("piles","欧几里得石堆","甲 乙",[21,15],"每步从大堆中减去小堆的一倍或多倍，结果保持正数。使两堆相等。",
       lambda a,b:a==b,lambda a,b:{str(n):((a-n*b,b) if a>b else (a,b-n*a)) for n in range(1,(max(a,b)-1)//min(a,b)+1)})
puzzle("cutcake","矩形分巧","行 列 刀数",[4,6,0],"只能沿整条格线切一刀并保留其中一块。恰两刀留下六格正好 2×3 的巧克力。",
       lambda h,w,n:(h,w,n)==(2,3,2),lambda h,w,n:{**{f"横{i}":(i,w,n+1) for i in range(1,h)},**{f"纵{i}":(h,i,n+1) for i in range(1,w)}} if n<2 else {})

