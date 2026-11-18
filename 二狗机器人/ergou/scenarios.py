"""Small deterministic games. Each entry defines its own legal transitions and objective."""
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    category: str
    labels: tuple
    start: tuple
    goal: callable
    actions: callable
    instructions: str

    def choices(self,state):
        return {name:tuple(next_state) for name,next_state in self.actions(*state).items()
                if next_state is not None and tuple(next_state)!=tuple(state)
                and all(not isinstance(v,int) or -1000<=v<=1000 for v in next_state)}

    def describe(self,state):
        return "、".join(f"{k}={v}" for k,v in zip(self.labels,state))

    def move(self,board,text):
        choices=self.choices(board["state"])
        if text not in choices:
            raise ValueError("可行动作："+" / ".join(choices))
        state=choices[text]
        board["state"]=state
        won=self.goal(*state)
        return won,self.describe(state)+("" if won else "。可行动作："+" / ".join(self.choices(state)))

    def solution(self,limit=100000):
        queue=deque([self.start])
        previous={self.start:None}
        while queue and len(previous)<limit:
            state=queue.popleft()
            if self.goal(*state):
                path=[]
                while previous[state]:
                    state,move=previous[state]
                    path.append(move)
                return list(reversed(path))
            for move,new in self.choices(state).items():
                if new not in previous:
                    previous[new]=(state,move)
                    queue.append(new)
        raise ValueError(self.name+" 无可验证解")


SCENARIOS=[]


def add(id,name,category,labels,start,instructions,goal,actions):
    SCENARIOS.append(Scenario(id,name,category,tuple(labels.split()),tuple(start),goal,actions,instructions))


def spin(word,n=1):
    return word[n:]+word[:n]


def swap(word,i,j):
    letters=list(word)
    letters[i],letters[j]=letters[j],letters[i]
    return "".join(letters)


def replace_at(word,i,c):
    return word[:i]+c+word[i+1:]


def water(level,cap):
    return min(cap,max(0,level))


def puzzle(id,name,labels,start,instructions,goal,actions):
    add(id,name,"猜题",labels,start,instructions,goal,actions)


def words(id,name,labels,start,instructions,goal,actions):
    add(id,name,"文字互动",labels,start,instructions,goal,actions)


def sim(id,name,labels,start,instructions,goal,actions):
    add(id,name,"模拟养成",labels,start,instructions,goal,actions)


# Logic and board games
puzzle("peg","跳棋留子","棋盘",["1101101"],"1 是棋子。跨一枚相邻棋子跳入空位，并提走被跨的棋子，留两枚。输入行动列表中的起点和方向。",
       lambda b:b.count("1")==2,lambda b:{f"{i+1}{'右' if d==1 else '左'}":(replace_at(replace_at(replace_at(b,i,'0'),i+d,'0'),i+2*d,'1'),)
       for i in range(len(b)) for d in (1,-1) if 0<=i+2*d<len(b) and b[i]==b[i+d]=='1' and b[i+2*d]=='0'})
puzzle("frogs","青蛙换岸","石列",["AA_BB"],"A 只向右，B 只向左。可走一步或跳过一只异色蛙，交换两队的位置。",
       lambda b:b=="BB_AA",lambda b:{str(i+1):(swap(b,i,b.index("_")),) for i,c in enumerate(b) if c in "AB"
       and (b.index("_")-i)*(1 if c=="A" else -1) in (1,2) and (abs(b.index("_")-i)==1 or b[(i+b.index("_"))//2]!=c)})
puzzle("tile","滑块复位","盘面",["1_3425"],"盘面按两行三列排列，用与空位相邻的数字滑块复原 12345_。",
       lambda b:b=="12345_",lambda b:{c:(swap(b,i,b.index("_")),) for i,c in enumerate(b)
       if abs(i//3-b.index("_")//3)+abs(i%3-b.index("_")%3)==1})
puzzle("bridge","限时过桥","左岸 手电 耗时",["1236",0,0],"人员耗时 1、2、3、6，每次一或两人带灯过桥，耗时取最慢者。13 分钟内全员到右岸。",
       lambda left,side,t:not left,lambda left,side,t:{
       pair:("".join(c for c in "1236" if (c in left)!=(c in pair)),1-side,t+max(map(int,pair)))
       for pair in ("1","2","3","6","12","13","16","23","26","36") if all((c in left)==(side==0) for c in pair) and t+max(map(int,pair))<=13})
puzzle("nim","取石对弈","剩石",[10],"每次取 1–3 石，机器人优先给你留下 4 的倍数，取最后一枚获胜。若机器人可清空堆则这步无效。",
       lambda n:n==0,lambda n:{str(k):(0 if n==k else n-k-((n-k)%4 or 1),) for k in (1,2,3) if k<=n and (k==n or n-k>3)})
puzzle("gray","格雷锁","锁码",[0],"三位锁；最低位随时可翻，更高位只有紧邻低位为 1 且再低位全为 0 时可翻。把锁码从 0 改为 4。",
       lambda n:n==4,lambda n:{str(i+1):(n^(1<<i),) for i in range(3) if i==0 or n%2**i==2**(i-1)})
puzzle("queens","四后布阵","各行列号",[""],"逐行放四枚皇后，每次输入列号 1–4，不得同列同斜线；撤销可退一行。",
       lambda s:len(s)==4,lambda s:{"撤销":(s[:-1],),**{str(c):(s+str(c),) for c in range(1,5) if str(c) not in s and all(abs(int(v)-c)!=len(s)-i for i,v in enumerate(s))}})
puzzle("knight","骑士巡灯","所在格 已访格",[0,"0"],"3×3 宫格从左上开始，按 1–9 行优先编号。骑士走日字，不重复踩格，点亮八个外围格。",
       lambda p,s:len(s)==8,lambda p,s:{str(i+1):(i,s+str(i)) for i in range(9) if str(i) not in s and {abs(p//3-i//3),abs(p%3-i%3)}=={1,2}})
puzzle("euler","一笔画桥","位置 已过边",["A",""],"图含 AB、BC、CA、AD、DC。从 A 出发每边恰走一次。输入目的地。",
       lambda p,s:len(s)==5,lambda p,s:{edge.replace(p,""):(edge.replace(p,""),s+str(i)) for i,edge in enumerate(("AB","BC","CA","AD","DC")) if p in edge and str(i) not in s})
puzzle("maze","钥匙迷宫","位置 钥匙",["门厅",0],"到书房取钥匙，经走廊开门，从出口离开。输入目的地或拾取。",
       lambda p,k:p=="出口",lambda p,k:{**{n:(n,k) for n in {"门厅":["书房","走廊"],"书房":["门厅"],"走廊":["门厅"]}.get(p,[])},
       "拾取":("书房",1) if p=="书房" else None,"开锁":("出口",k) if p=="走廊" and k else None})
puzzle("stack","车厢调序","进站 侧线 发车",["ABC","",""],"入口 ABC，只能经单条后进先出侧线调车，出站目标 BAC。",
       lambda a,b,c:c=="BAC",lambda a,b,c:{"进侧线":(a[1:],b+a[0],c) if a else None,"发车":(a,b[:-1],c+b[-1]) if b and "BAC".startswith(c+b[-1]) else None})
puzzle("scale","砝码天平","未放 差值",["139",-5],"天平左边有 5，手上有 1、3、9，每枚可选左盘或右盘。让差值为零。",
       lambda s,n:n==0,lambda s,n:{side+c:(s.replace(c,""),n+d*int(c)) for c in s for side,d in (("左",-1),("右",1))})
puzzle("counterfeit","天平辨伪","候选 称量结果",["123456789","未称"],"九枚币中一枚偏重。把候选按三等份上天平，输入要放左、右盘的段号（例如 12）。依据倾斜或平衡缩小候选。",
       lambda coins,result:len(coins)==1,lambda coins,result:weigh_coins(coins))


def weigh_coins(coins):
    if len(coins)==1:return {}
    size=len(coins)//3
    thirds=[coins[i:i+size] for i in range(0,len(coins),size)]
    heavy=next(i for i,part in enumerate(thirds) if "7" in part)
    return {f"{a+1}{b+1}":(thirds[heavy],"左重" if heavy==a else "右重" if heavy==b else "平衡")
            for a in range(3) for b in range(3) if a!=b}
puzzle("bucket","漏水计时","沙漏三 沙漏五 时刻",[0,0,0],"可翻转 3、5 分沙漏；流逝会跳至下一只漏完的时刻。准确停在第 7 分钟。",
       lambda a,b,t:t==7,lambda a,b,t:{"翻三":(3-a,b,t),"翻五":(a,5-b,t),"流逝":(max(0,a-min(v for v in (a,b) if v)),max(0,b-min(v for v in (a,b) if v)),t+min(v for v in (a,b) if v)) if (a or b) and t<7 else None})
puzzle("fuse","导线转向","入口 弯管 出口",[0,0,0],"顺时针旋入口连动弯管，旋弯管逆向连动出口，出口仅可半转。把三节方向调成 1、2、1。",
       lambda a,b,c:(a,b,c)==(1,2,1),lambda a,b,c:{"入口":((a+1)%4,(b+1)%4,c),"弯管":(a,(b+1)%4,(c-1)%4),"出口":(a,b,(c+2)%4)})
puzzle("sieve","素数筛","候选",["2,3,4,5,6,7,8,9,10,11,12"],"选择尚在表中的素数筛去其余倍数，直到表中只剩素数。",
       lambda s:s=="2,3,5,7,11",lambda s:{str(p):(",".join(x for x in s.split(",") if int(x)==p or int(x)%p),) for p in (2,3,5,7,11)})
puzzle("balance","均分筹码","左 中 右",[0,6,3],"每步可把最多那堆的一枚筹码移向相邻堆，使三堆相等。",
       lambda a,b,c:a==b==c,lambda a,b,c:{"左到中":(a-1,b+1,c) if a==max(a,b,c) else None,"中到左":(a+1,b-1,c) if b==max(a,b,c) else None,
       "中到右":(a,b-1,c+1) if b==max(a,b,c) else None,"右到中":(a,b+1,c-1) if c==max(a,b,c) else None})
puzzle("paths","格点避障","横 纵",[0,0],"在 4×4 点阵走到 (3,3)。禁止 (1,1)、(1,2)、(3,1)，只向右、上或斜跳两格。",
       lambda x,y:(x,y)==(3,3),lambda x,y:{k:(x+a,y+b) for k,a,b in (("右",1,0),("上",0,1),("跳",2,1)) if x+a<4 and y+b<4 and (x+a,y+b) not in ((1,1),(1,2),(3,1))})
puzzle("pour","分层色管","甲 乙 丙",["红蓝","蓝红",""],"每管容两珠，从一管顶部倒一珠到空管或同色顶珠上，形成红红和蓝蓝两管。",
       lambda *v:"红红" in v and "蓝蓝" in v,lambda *v:{"甲乙丙"[a]+"甲乙丙"[b]:tuple(s[:-1] if i==a else s+v[a][-1] if i==b else s for i,s in enumerate(v))
       for a in range(3) for b in range(3) if a!=b and v[a] and len(v[b])<2 and (not v[b] or v[a][-1]==v[b][-1])})
puzzle("ice","冰面滑行","格号",[0],"4×4 冰面，格号从 0 行优先。滑向一边直到碰壁；5、9、11 为石块。停在格 14。",
       lambda p:p==14,lambda p:ice_moves(p))


def ice_moves(p):
    moves={}
    for k,dx,dy in (("左",-1,0),("右",1,0),("上",0,-1),("下",0,1)):
        x,y=p%4,p//4
        while 0<=x+dx<4 and 0<=y+dy<4 and (y+dy)*4+x+dx not in (5,9,11):
            x,y=x+dx,y+dy
        moves[k]=(y*4+x,)
    return moves

