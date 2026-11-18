"""Text actions on words, symbols, and story state."""
from .scenarios import words, spin, swap, replace_at


words("pal","回文工匠","字串 剪刀",["上海自海上岸",1],"只可剪去两端之一，一剪做出长度五的回文。",
      lambda s,k:len(s)==5 and s==s[::-1],lambda s,k:{"剪左":(s[1:],k-1) if k else None,"剪右":(s[:-1],k-1) if k else None})
words("brackets","括号剧场","待入场 栈 演出",["([","", ""],"按顺序请两位演员入场，必须逆序谢幕，上演完整的嵌套剧情 ([])。",
      lambda todo,stack,show:show=="([])",lambda todo,stack,show:{"入场":(todo[1:],stack+todo[0],show+todo[0]) if todo else None,
      "谢幕":(todo,stack[:-1],show+{"(":")","[":"]"}[stack[-1]]) if stack and (not todo or len(stack)>1) else None})
words("morse","电报码手","当前码 已译",["",""],"点、划组成国际摩尔斯码，分隔键译出一字母。发出 SOS。S 是三点，O 是三划。",
      lambda code,s:s=="SOS",lambda code,s:{"点":(code+".",s) if len(code)<3 else None,"划":(code+"-",s) if len(code)<3 else None,
      "重打":("",s),"分隔":("",s+{"...":"S","---":"O"}[code]) if code in ("...","---") and "SOS".startswith(s+{"...":"S","---":"O"}[code]) else None})
words("zip","游程解包","指令 纸带",["3A2B1C",""],"逐段读次数和字母，选正确长度的字块还原压缩纸带。",
      lambda todo,s:not todo and s=="AAABBC",lambda todo,s:{todo[1]*int(todo[0]):(todo[2:],s+todo[1]*int(todo[0]))} if todo else {})
words("weave","双线织字","经线 纬线 成品",["春花","风开",""],"交替从经纬两条队列取字，织成「春风花开」。",
      lambda a,b,s:s=="春风花开",lambda a,b,s:{"经":(a[1:],b,s+a[0]) if a else None,"纬":(a,b[1:],s+b[0]) if b else None})
words("type","退格修稿","光标左 光标右",["青山在","在"],"移动光标、退格或补字，将「青山在在」改为「青山常在」。",
      lambda l,r:l+r=="青山常在",lambda l,r:{"左移":(l[:-1],l[-1]+r) if l else None,"右移":(l+r[0],r[1:]) if r else None,
      "退格":(l[:-1],r) if l else None,"补常":(l+"常",r) if len(l+r)<5 else None})
words("sandwich","夹心构词","词坯 内字",["门",""],"选择内字装进门框，在词库中组合，再选择搭档成词。目标「问候」。",
      lambda frame,inner:frame=="问候",lambda frame,inner:{"放口":(frame,"口") if frame=="门" else None,"放日":(frame,"日") if frame=="门" else None,
      "合字":({"口":"问","日":"间"}[inner],"") if frame=="门" and inner else None,"配候":("问候","") if frame=="问" else None,"拆开":("门","")})
words("fold","纸条折叠","纸条",["ABCCBA"],"若两端字符相同可对折剥去一层，若不同可左旋；折空纸条。",
      lambda s:not s,lambda s:{"对折":(s[1:-1],) if len(s)>1 and s[0]==s[-1] else None,"左旋":(spin(s),)})
words("erase","相邻消消字","纸带",["ABBACC"],"点选一种字母，一次消除其第一对相邻重复字母，将纸带消空。",
      lambda s:not s,lambda s:{c:(s.replace(c+c,"",1),) for c in set(s) if c+c in s})
words("rewrite","文法炼金","符号串",["S"],"从 S 开始，可将首个 S 展成 aSb 或空串，生成 aaabbb。",
      lambda s:s=="aaabbb",lambda s:{"展开":(s.replace("S","aSb",1),) if "S" in s and len(s)<8 else None,"封口":(s.replace("S","",1),)})
words("boggle","九宫寻词","路径",[""],"棋盘 CAT/REO/SUN，沿相邻八方向连成 CARE，格子不得复用，输入字母。",
      lambda s:s=="CARE",lambda s:{c:(s+c,) for i,c in enumerate("CATREOSUN") if c not in s and "CARE".startswith(s+c)
      and (not s or max(abs(i//3-"CATREOSUN".index(s[-1])//3),abs(i%3-"CATREOSUN".index(s[-1])%3))==1)})
words("anagram","前缀翻牌","手牌",["CABD"],"每步只能将前 2、3 或 4 张牌翻转，整理成 ABCD。",
      lambda s:s=="ABCD",lambda s:{str(i):(s[:i][::-1]+s[i:],) for i in (2,3,4)})
words("rag","报头拼贴","报头 剪下",["今日晴天适合远行",""],"从报头左端依次取字或丢弃，拼成「今天远行」。",
      lambda s,w:w=="今天远行",lambda s,w:{"取":(s[1:],w+s[0]) if s else None,"弃":(s[1:],w) if s else None})
words("subway","地名换乘","地点 线路 换乘",["北门","红",0],"红线北门—钟楼—江口，蓝线西岸—钟楼—书院。在钟楼换线，到书院。",
      lambda p,l,t:p=="书院" and t==1,lambda p,l,t:{**{n:(n,l,t) for seq in [("北门","钟楼","江口") if l=="红" else ("西岸","钟楼","书院")] for n in seq if abs(seq.index(n)-seq.index(p))==1},
      "换乘":(p,"蓝" if l=="红" else "红",t+1) if p=="钟楼" and t<2 else None})
words("story","分支侦探","线索 证言",["",0],"调查钟表店：找停表、采集足印、用两份独立证据核对证言，最后指认。",
      lambda clues,s:s==2,lambda clues,s:{"查钟":("钟"+clues,s) if "钟" not in clues else None,"验足迹":(clues+"印",s) if "印" not in clues else None,
      "核对":(clues,1) if len(clues)==2 else None,"指认":(clues,2) if s==1 else None})
words("echo","回声记谱","谱 游标",["高低低高",0],"逐拍用高低反唱：原谱高低低高，高唱低，低唱高。唱错回到首拍。",
      lambda s,i:i==len(s),lambda s,i:{c:(s,i+1 if c!=s[i] else 0) for c in ("高","低")} if i<len(s) else {})
words("rhyme","押韵换轨","韵脚 诗句",["ang",""],"每句选与韵脚相配的末字，转韵会消耗一个停顿。按「江、光、舟」收束三句。江/光属 ang，舟属 ou。",
      lambda r,s:s=="江光舟",lambda r,s:{**{c:(r,s+c) for c,need in (("江","ang"),("光","ang"),("舟","ou")) if r==need and "江光舟".startswith(s+c)},
      "转韵":("ou" if r=="ang" else "ang",s)})
words("radical","偏旁拆装","零件 成品",["木木日月",""],"用两个木合林，用日月合明；可以拆掉最近合成的字，拼出「明林」。",
      lambda parts,s:s=="明林",lambda p,s:{**{a:(p.replace(b[0],"",1).replace(b[1],"",1),s+a) for a,b in (("林","木木"),("明","日月")) if all(p.count(c)>=b.count(c) for c in b)},
      "拆":(p+{"林":"木木","明":"日月"}[s[-1]],s[:-1]) if s else None})
words("cut","断句排版","未读 版面",["研究生命起源",""],"用词典逐段切词，切成三个合法词并读完整句；可撤销上一词。",
      lambda p,s:not p and s.count("/")==3,lambda p,s:{**{w:(p[len(w):],s+w+"/") for w in ("研究","研究生","生命","起源") if p.startswith(w)},
      "撤销":(s[:-1].split("/")[-1]+p,s[:-(len(s[:-1].split("/")[-1])+1)]) if s else None})
words("debate","论证接力","论证链",[""],"组装有依赖关系的论证，先给事实和定义，再推导，最后结论。允许撤回最后一环。",
      lambda s:s.endswith("结"),lambda s:{**{w:(s+w,) for w,needs in (("事",""),("定",""),("推","事定"),("结","推")) if w not in s and all(c in s for c in needs)},"撤回":(s[:-1],)})
words("acrostic","藏头排诗","诗行 次序",["海山日",""],"把三行按藏头「山海日」排版。只能将队首诗行移到队尾或收入定稿。",
      lambda q,s:s=="山海日",lambda q,s:{"轮转":(spin(q),s),"定稿":(q[1:],s+q[0]) if q and "山海日".startswith(s+q[0]) else None})
words("rail","栅栏密信","上轨 下轨 明文",["夜看","星河",""],"拆开双轨栅栏密信，每轮从指定轨首字复原「夜星看河」；也可把两轨交换。",
      lambda a,b,s:s=="夜星看河",lambda a,b,s:{"取上":(a[1:],b,s+a[0]) if a else None,"换轨":(b,a,s)})
words("hang","猜字揭幕","已试 失误",["",0],"秘密词是一种三字母宠物（英文大写）。每次试一字母，依次揭出 C、A、T 的位置，最多两次失误。",
      lambda s,k:all(c in s for c in "CAT"),lambda s,k:{c:("".join(sorted(s+c)),k+int(c not in "CAT")) for c in "CATDOG" if c not in s and (c in "CAT" or k<2)})
words("affix","词缀制造","词根",["play"],"先加可用后缀再加前缀，制造 replaying。ing/er 加在 play 之后，re 加在动词或分词之前。",
      lambda s:s=="replaying",lambda s:{"加ing":(s+"ing",) if s=="play" else None,"加er":(s+"er",) if s=="play" else None,
      "加re":("re"+s,) if s in ("play","playing") else None,"去词缀":("play",)})
words("mirror","镜面对话","对话",["ab"],"镜面会复制当前整句话的倒序；分句可截去首字，续句可追加 c。构造 abccba。",
      lambda s:s=="abccba",lambda s:{"照镜":(s+s[::-1],) if len(s)<=3 else None,"分句":(s[1:],) if s else None,"续句":(s+"c",) if len(s)<6 else None})
words("auction","拍卖叫价","价 预算 竞争", [1,7,2],"竞争者会跟价两次，每次加一。可加一或跳价二；对手退出后落槌，守住预算。",
      lambda price,money,k:k==-1,lambda p,m,k:{**{f"加{n}":(p+n+int(k>0),m,max(0,k-1)) for n in (1,2) if k>0 and p+n+1<=m},
      "落槌":(p,m-p,-1) if k==0 and m>=p else None})
words("logicline","真假口供","候选",["甲乙丙丁"],"四个候选中用口供排除矛盾：排除夜班甲丙、排除左撇子丁。剩唯一人后点名。",
      lambda s:s=="定乙",lambda s:{"核班表":("".join(c for c in s if c not in "甲丙"),),"比笔迹":(s.replace("丁",""),),"点名":("定乙",) if s=="乙" else None})
words("domino","词牌骨龙","尾牌 手牌",["山","山水 水月 月明 明山"],"以手牌首字接龙，只用完全部词牌且末字回到山。可调转每张词牌方向。",
      lambda tail,hand:not hand and tail=="山",lambda tail,hand:{orientation:(orientation[1]," ".join(w for w in hand.split() if w!=card))
      for card in hand.split() for orientation in (card,card[::-1]) if orientation[0]==tail})
words("tape","打孔纸带","格号 纸带",[0,"0000"],"读写头每次可右移一格或写 1 后回到开头；打出 1011。",
      lambda i,s:s=="1011",lambda i,s:{"右移":((i+1)%4,s),"打孔":(0,replace_at(s,i,"1"))})
words("concord","索引校对","索引 待编",["","山水山月"],"逐字建立首次出现索引，重复字必须跳过。编完后索引应是山水月。",
      lambda s,q:not q and s=="山水月",lambda s,q:{"登记":(s+q[0],q[1:]) if q and q[0] not in s else None,"跳过":(s,q[1:]) if q and q[0] in s else None})
words("cipher","滚轮译码","偏移 游标 明文",[0,0,""],"密文 DBU，调偏移后逐字译出 CAT。译字后滚轮自动前进一位，须重新校准。",
      lambda n,i,s:s=="CAT",lambda n,i,s:{"调高":((n+1)%4,i,s),"调低":((n-1)%4,i,s),"译字":((n+1)%4,i+1,s+chr(ord("DBU"[i])-n)) if i<3 and chr(ord("DBU"[i])-n)=="CAT"[i] else None})

