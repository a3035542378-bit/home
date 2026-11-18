"""Resource and time simulations. Each legal command advances one decision."""
from .scenarios import sim, water


sim("bakery","面包作坊","面团 发酵 成品",[0,0,0],"揉面后静置两拍，第三拍会过度发酵。适时烘烤两炉。",
    lambda d,f,b:b==2,lambda d,f,b:{"揉面":(1,0,b) if not d else None,"静置":(int(f<2),f+1 if f<2 else 0,b) if d else None,"入炉":(0,0,b+1) if d and f==2 else None})
sim("reservoir","水库调洪","水位 汛期 放水量",[3,0,0],"四轮来水依次 2、4、1、3，每轮选放水 0–3。水位保持 1–6，汛末至少留 3。",
    lambda w,t,z:t==4 and w>=3,lambda w,t,z:{f"放{n}":(w+(2,4,1,3)[t]-n,t+1,z+n) for n in range(4) if 1<=w+(2,4,1,3)[t]-n<=6} if t<4 else {})
sim("bees","蜂群越冬","花蜜 工蜂 季节",[3,1,0],"每轮可采蜜（每工蜂两蜜）或消耗两蜜育蜂；每轮全群耗一蜜。五轮后留足八蜜。",
    lambda h,b,t:t==5 and h>=8,lambda h,b,t:{"采蜜":(h+2*b-1,b,t+1),"育蜂":(h-3,b+1,t+1) if h>=3 else None} if t<5 else {})
sim("clinic","分诊值班","病情甲 病情乙 已救治",[2,3,0],"治疗一位病人需减其病情两点，等待者病情升一点，不得超过 5；稳定到零者出院。",
    lambda a,b,n:a==b==0,lambda a,b,n:{"治甲":(max(0,a-2),b+int(b>0),n+int(a<=2)) if a and b<5 else None,"治乙":(a+int(a>0),max(0,b-2),n+int(b<=2)) if b and a<5 else None})
sim("orchard","果园嫁接","砧木 接穗 结合",[0,0,0],"分别培育砧木与接穗。粗度相等且均至少二时嫁接，之后绑扎、拆带。",
    lambda a,b,c:c==3,lambda a,b,c:{"育砧":(a+1,b,c) if c==0 and a<4 else None,"育穗":(a,b+1,c) if c==0 and b<4 else None,
    "嫁接":(a,b,1) if c==0 and a==b>=2 else None,"绑扎":(a,b,2) if c==1 else None,"拆带":(a,b,3) if c==2 else None})
sim("brew","调饮师","茶 奶 冰",[0,0,0],"茶每勺加二，奶每勺加一。摇匀会融一块冰并消耗一份茶。按茶三奶二冰一交杯。",
    lambda a,b,c:(a,b,c)==(3,2,1),lambda a,b,c:{"注茶":(a+2,b,c) if a<5 else None,"加奶":(a,b+1,c) if b<3 else None,"加冰":(a,b,c+1) if c<3 else None,"摇匀":(a-1,b,c-1) if a and c else None})
sim("loom","织机学徒","梭位 线色 花纹",[0,"红",""],"梭位往复，左端可换色。每抛一次梭织一格，织出红红蓝蓝。",
    lambda p,c,s:s=="红红蓝蓝",lambda p,c,s:{"换线":(p,"蓝" if c=="红" else "红",s) if p==0 else None,"抛梭":(1-p,c,s+c) if len(s)<4 else None,"拆布":(1-p,c,s[:-1]) if s else None})
sim("cafe","咖啡轮班","排队 出杯机 收款",[3,0,0],"可预制两杯浓缩，再逐杯加奶交付。每服务两人有一位新客，累计服务四人。",
    lambda q,b,s:s==4,lambda q,b,s:{"萃取":(q,b+1,s) if b<2 else None,"交付":(q-1+int(s%2==1),b-1,s+1) if b and q else None})
sim("bus","公交排班","站点 空座 已运",[0,3,0],"循环三站：起点上客至满，第二站可接一人，终点全部下车。运送五人次。",
    lambda p,s,n:n>=5,lambda p,s,n:{"上车":(p,s-1,n) if p<2 and s else None,"行车":((p+1)%3,s,n),"下车":(p,3,n+3-s) if p==2 and s<3 else None})
sim("solar","光伏微网","电池 白昼 供电",[0,1,0],"白昼可将两度电存入电池。推进半日切换昼夜；夜间每次照明耗两度，照亮两个夜晚。",
    lambda e,d,n:n==2,lambda e,d,n:{"蓄电":(min(4,e+2),d,n) if d==1 else None,"过半日":(e,1 if d==0 else 0,n),"夜灯":(e-2,2,n+1) if d==0 and e>=2 else None})
sim("compost","堆肥箱","碳料 氮料 熟度",[0,0,0],"干叶提供两份碳，鲜草提供一份氮；以 2:1 配料翻堆两轮，熟度到二。",
    lambda c,n,m:m==2,lambda c,n,m:{"投叶":(min(6,c+2),n,m),"投草":(c,min(3,n+1),m),"翻堆":(c-2,n-1,m+1) if c==2*n and n else None})
sim("forge","锻刀控温","温度 形变 硬度",[0,0,0],"加热升三度，锻打在温度 3–6 时消耗两度并形成刀胚。锻两次后趁热淬火。",
    lambda t,s,h:h==1,lambda t,s,h:{"加热":(min(8,t+3),s,h),"冷却":(max(0,t-1),s,h),"锻打":(t-2,s+1,h) if 3<=t<=6 and s<2 else None,"淬火":(0,s,1) if s==2 and t>=4 else None})
sim("pottery","陶坯成器","湿度 壁厚 窑温",[3,4,0],"湿度至少二时拉坯，拉坯同时减湿和减薄。厚度二时晾干，分两段烧成。",
    lambda m,w,k:k==2,lambda m,w,k:{"润坯":(min(4,m+1),w,k) if not k else None,"拉坯":(m-1,w-1,k) if m>=2 and w>2 else None,
    "晾干":(max(0,m-1),w,k),"升窑":(m,w,k+1) if m==0 and w==2 and k<2 else None})
sim("aquarium","鱼缸平衡","鱼 氧 藻",[1,3,1],"光照让藻繁殖，藻供氧。增一条鱼耗两氧并吃一藻。平衡缸内三鱼、至少两氧。",
    lambda f,o,a:f==3 and o>=2,lambda f,o,a:{"光照":(f,min(6,o+a),min(3,a+1)),"添鱼":(f+1,o-2,a-1) if f<3 and o>=2 and a else None,"打氧":(f,min(6,o+1),a)})
sim("stock","货架补给","库存 在途 日序",[2,0,0],"四天需求 1、2、1、2。每次开店先收昨日订单再满足需求，同时可订 0–2 件。末日零库存。",
    lambda s,p,d:d==4 and s==p==0,lambda s,p,d:{f"订{n}":(s+p-(1,2,1,2)[d],n,d+1) for n in range(3) if s+p>=(1,2,1,2)[d]} if d<4 else {})
sim("library","图书流转","在架 外借 预约",[2,0,2],"两本书借给两位预约人，归还必须先经还书箱，再归架；预约清空后两本全部上架。",
    lambda shelf,loan,res:res==0 and shelf==2,lambda s,l,r:{"借出":(s-1,l+1,r-1) if s and r else None,"归还":(s,l-1,r) if l else None,"上架":(s+1,l,r) if s+l<2 else None})
sim("harbor","港口起重机","吊钩 甲板 岸货",["空","","重轻"],"船舱只允许重箱在下。岸边先到重箱，吊钩一次移动一箱。两箱按重轻装船。",
    lambda h,d,c:d=="重轻",lambda h,d,c:{"起吊":(c[0],d,c[1:]) if h=="空" and c else None,"落箱":("空",d+h,c) if h!="空" and (not d or h=="轻") else None,
    "卸箱":(d[-1],d[:-1],c) if h=="空" and d else None})
sim("train","会车调度","东车 西车 侧线",["西","东","空"],"一段单线有会让侧线。先让东行车进中段并避让，放西行车穿过，再驶出东行车。",
    lambda a,b,s:a=="东" and b=="西",lambda a,b,s:{"东车进":("中",b,s) if a=="西" and b!="中" else None,"东车让":("侧",b,"占") if a=="中" else None,
    "西车进":(a,"中",s) if b=="东" and a!="中" else None,"西车出":(a,"西",s) if b=="中" and a!="西" else None,
    "东车回":("中",b,"空") if a=="侧" and b!="中" else None,"东车出":("东",b,s) if a=="中" and b!="东" else None})
sim("watermill","水轮磨坊","水闸 转速 面粉",[0,0,0],"调闸改变加速幅度，转轮累加闸位。转速恰三可磨粉，磨完转速归一；磨两袋。",
    lambda gate,v,f:f==2,lambda g,v,f:{"调闸":((g+1)%3,v,f),"转轮":(g,min(5,v+g),f),"刹车":(g,max(0,v-1),f),"磨粉":(g,1,f+1) if v==3 else None})
sim("camera","暗房冲印","曝光 显影 定影",[0,0,0],"选一档或两档曝光，曝光三档时显影，显影两拍后才可定影。",
    lambda e,d,f:f==1,lambda e,d,f:{"一档":(e+1,d,f) if not d and e<4 else None,"两档":(e+2,d,f) if not d and e<3 else None,
    "显影":(e,d+1,f) if e==3 and d<2 else None,"定影":(e,d,1) if d==2 else None})
sim("balloon","热气球航线","高度 横距 燃料",[0,0,5],"上升耗燃料，不同高度风速不同。每漂移一次增加当前高度的横距；在横距五处降落。",
    lambda h,x,f:h==0 and x==5,lambda h,x,f:{"升空":(h+1,x,f-1) if h<3 and f else None,"下降":(h-1,x,f) if h else None,"乘风":(h,x+h,f) if h and x+h<=5 else None})
sim("moon","月面着陆","高度 下速 燃料",[6,1,4],"每拍重力使下速加一，点火抵消两点速度。到零高度时下速最多一。",
    lambda h,v,f:h==0 and v<=1,lambda h,v,f:{cmd:(h-max(0,v+1-2*b),max(0,v+1-2*b),f-b) for cmd,b in (("滑落",0),("点火",1)) if f>=b and h>0 and h>=max(0,v+1-2*b)})
sim("tide","潮汐采珠","潮位 珍珠 船位",[0,0,0],"潮位按 0、1、2、1 循环。涨潮出船，低潮潜水取珠，满潮才可返港。",
    lambda t,p,b:p>=1 and b==0,lambda t,p,b:{"等潮":((t+1)%4,p,b),"出海":((t+1)%4,p,1) if t==1 and not b else None,
    "采珠":((t+1)%4,p+1,b) if t==0 and b and p<2 else None,"回港":((t+1)%4,p,0) if t==2 and b else None})
sim("fire","林火隔离","火线 隔离带 水量",[0,0,2],"火向前推进，挖带同时推进一格；两段隔离带可阻燃，再用一桶水扑灭。喷水可先减缓火线。",
    lambda f,b,w:f==-1,lambda f,b,w:{"挖带":(f+1,b+1,w) if f<3 and b<2 else None,"喷水":(-1 if b==2 else max(0,f-1),b,w-1) if w else None})
sim("forest","林地演替","幼苗 成树 种子",[0,0,2],"播种用一枚种子。生长令所有幼苗成树，每次采种产生与成树等量的种子。培育四株成树。",
    lambda s,t,k:t>=4,lambda s,t,k:{"播种":(s+1,t,k-1) if k and s<4 else None,"生长":(0,t+s,k) if s else None,"采种":(s,t,min(6,k+t)) if t else None})
sim("battery","电池均衡","甲 乙 热量",[6,0,0],"由甲向乙充一格会积一热，两热后须散热。将两块都调成三格且温度归零。",
    lambda a,b,h:(a,b,h)==(3,3,0),lambda a,b,h:{"转充":(a-1,b+1,h+1) if a and h<2 else None,"散热":(a,b,max(0,h-1))})
sim("reef","珊瑚修复","沙量 固着 群落",[3,0,0],"先以清沙开辟地基。挂苗消耗一个清洁位，成群固着的两株可繁育一片礁群。",
    lambda s,a,r:r==2,lambda s,a,r:{"清沙":(max(0,s-1),a,r),"挂苗":(s,a+1,r) if s+a<3 else None,"繁育":(min(3,s+1),a-2,r+1) if a>=2 else None})
sim("museum","展厅策展","预算 展品 导览",[5,"",0],"展品文物费三、画作费二、拓片费一。选两件不同展品且留一份预算印导览。",
    lambda m,s,g:g==1,lambda m,s,g:{**{k:(m-cost,s+k,g) for k,cost in (("器",3),("画",2),("帖",1)) if k not in s and m>=cost and len(s)<2},
    "导览":(m-1,s,1) if len(s)==2 and m else None})
sim("kitchen","双灶晚餐","汤剩时 饭剩时 时刻",[-1,-1,0],"汤炖三拍，饭焖两拍。分别开灶，等待推进两锅，要求两道菜同拍完成，已熟再等会过熟。",
    lambda a,b,t:a==b==0,lambda a,b,t:{"炖汤":(3,b,t) if a==-1 else None,"焖饭":(a,2,t) if b==-1 else None,
    "等候":(a-1 if a>=0 else a,b-1 if b>=0 else b,t+1) if t<5 and a!=0 and b!=0 else None})
sim("elevator","电梯节能","层数 载客 电量",[1,0,6],"一楼和二楼各一名乘客（以位标记），四楼送达。上行每层耗一，空载下降再生一。",
    lambda f,m,e:f==4 and m==7,lambda f,m,e:{"载客":(f,m|(1<<(f-1)),e) if f in (1,2) else None,"上":(f+1,m,e-1) if f<4 and e else None,
    "下":(f-1,m,min(6,e+int(m==0))) if f>1 else None,"送达":(f,7,e) if f==4 and m==3 else None})
sim("radio","电台调谐","粗调 微调 噪声",[0,0,3],"粗调五档，微调三档，频点为粗×3+微。调到 7 后校准两次降低噪声，再锁频。",
    lambda c,f,n:n==0,lambda c,f,n:{"粗调":((c+1)%5,f,3),"微调":(c,(f+1)%3,3),"校准":(c,f,n-1) if c*3+f==7 and n>1 else None,"锁频":(c,f,0) if n==1 else None})
sim("rover","火星采样","位置 载样 电量",[0,0,6],"从基地往返三格外岩点，移动耗电。白色岩点取样，能量恰可往返。",
    lambda p,s,e:p==0 and s==1,lambda p,s,e:{"前进":(p+1,s,e-1) if p<3 and e else None,"后退":(p-1,s,e-1) if p and e else None,"钻取":(p,1,e) if p==3 else None})
sim("trainpet","伙伴训练","体力 技巧 默契",[3,0,0],"训练耗两体力长技巧；互动耗一体力长默契，休整恢复两体力。技巧二、默契二后完成合演。",
    lambda e,s,b:s==3,lambda e,s,b:{"训练":(e-2,s+1,b) if e>=2 and s<2 else None,"互动":(e-1,s,min(2,b+1)) if e else None,
    "休整":(min(3,e+2),s,b),"合演":(e,3,b) if s==b==2 else None})
sim("canal","船闸运行","闸水位 船所在 门",[0,"下游","闭"],"船入低水位闸，关门蓄水至二，开上门驶出；开门时不能改变水位。",
    lambda w,p,d:p=="上游",lambda w,p,d:{"下门":(w,p,"下") if w==0 and d=="闭" else None,"入闸":(w,"闸内",d) if d=="下" and p=="下游" else None,
    "闭门":(w,p,"闭"),"蓄水":(min(2,w+1),p,d) if d=="闭" else None,"上门":(w,p,"上") if w==2 and d=="闭" else None,
    "出闸":(w,"上游",d) if d=="上" and p=="闸内" else None})
sim("sail","迎风航行","横距 纵距 舷",[0,0,1],"迎风时需之字抢风，一航步前进一格并向当前舷横移一格。到横距零、纵距四的浮标。",
    lambda x,y,d:(x,y)==(0,4),lambda x,y,d:{"换舷":(x,y,-d),"抢风":(x+d,y+1,d) if y<4 and abs(x+d)<=2 else None})
sim("print","套色印刷","套版 层次 位置",[0,"",0],"分别对齐红蓝版。红版位置 1，蓝版位置 2。按红后蓝压印，中途可换版调位。",
    lambda p,s,x:s=="红蓝",lambda p,s,x:{"换版":(1-p,s,x),"移纸":(p,s,(x+1)%3),"压印":(p,s+("红","蓝")[p],x) if x==p+1 and len(s)<2 else None})
sim("traffic","路口配时","东西 南北 相位",[3,2,0],"绿灯每次放两车，切换方向需黄灯过渡。将两方向队列全部疏散。",
    lambda a,b,p:a==b==0,lambda a,b,p:{"切相":(a,b,(p+1)%4),"放行":(max(0,a-2),b,p) if p==0 else (a,max(0,b-2),p) if p==2 else None})
sim("telescope","观星排程","时段 已拍 余电",[0,"",4],"四时段里月面仅 0/2 可见，星云仅 1/3 可见。满电四格，月面耗一，星云耗二；都拍到即可。",
    lambda t,s,e:len(s)==2,lambda t,s,e:{"等候":(t+1,s,e) if t<3 else None,"拍月":(t+1,s+"月",e-1) if t in (0,2) and "月" not in s and e else None,
    "拍云":(t+1,s+"云",e-2) if t in (1,3) and "云" not in s and e>=2 else None})
sim("hydro","配液栽培","酸度 浓度 生叶",[5,1,0],"滴碱升酸碱值，营养盐降一并加浓度。维持 pH 6–7、浓度二以上才能生叶，每片叶耗一浓度。",
    lambda p,c,l:l==2,lambda p,c,l:{"滴碱":(min(8,p+1),c,l),"加盐":(max(4,p-1),min(4,c+1),l),"生叶":(p,c-1,l+1) if 6<=p<=7 and c>=2 else None})
sim("recycle","回收分拣","传送带 金属 纸浆",["纸铁纸铁",0,0],"按传送带队首投料，磁选铁、制浆纸。每制两份纸浆可打包；攒两铁并打包。",
    lambda q,m,p:not q and m==2 and p==3,lambda q,m,p:{"磁选":(q[1:],m+1,p) if q.startswith("铁") else None,"制浆":(q[1:],m,p+1) if q.startswith("纸") else None,
    "打包":(q,m,3) if p==2 else None})

