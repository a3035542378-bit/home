"""Small offline conversation set. Persist only topic codes so follow-ups survive restarts."""
import re


TOPICS = {
    "joke": (("笑话", "逗我", "搞笑"),
             ("二狗去面试。老板问有什么特长，我说：一听见「开饭」，我能从睡梦中直接上岗。",
              "昨天我向扫地机器人认错了。它绕开我走了三圈，看样子还在生气。",
              "我报了个早睡打卡群。第一天大家聊怎么早睡，一抬头已经凌晨一点。")),
    "story": (("故事","童话"),
              ("雨夜，柴犬捡到一把比自己还小的伞。它把伞插在花盆里，第二天伞底下多了一双泥脚印。想听后续就说「二狗然后呢」。",
               "二狗顺着泥脚印走，遇到一只扛着蒲公英的小青蛙。青蛙说：「昨天借了你的屋顶，今天来给你送一盏灯。」",
               "夜里，萤火虫落在蒲公英上。二狗和青蛙守着小伞，第一次发现，屋檐小一点，也装得下星光。故事讲完啦。")),
    "tired": (("好累","太累","累了","疲惫","加班"),
              ("今天辛苦啦。二狗在这儿陪你歇会儿，是事情太多，还是有件事特别耗神？",
               "那就先把最耗神的那件事搁一会儿。二狗趴在你脚边，等你慢慢说。")),
    "sad": (("难过","伤心","不开心","委屈","心情不好"),
            ("二狗搬个小板凳坐你旁边。今天发生什么事了？",
             "我听着呢。你最希望当时有人对你说什么？")),
    "hello": (("你好","在吗","嗨","早安","晚安"),
              ("汪，在呢！想玩一局成语接龙，还是看看今天的运势？",)),
}


def respond(db,event,text,*,fallback=None):
    key=(event["grp"],event["member"],event["binding"])
    rows=db.execute("""SELECT topic,at FROM local_turns WHERE grp=? AND member=? AND binding=?
                       ORDER BY seq DESC LIMIT 16""",key).fetchall()
    if rows and event["arrived"]-rows[0]["at"]>=1800:
        db.execute("DELETE FROM local_turns WHERE grp=? AND member=? AND binding=?",key)
        rows=[]
    topic=next((topic_name for topic_name,(words,_) in TOPICS.items() if any(w in text for w in words)),None)
    if topic is None and rows and re.fullmatch(r"(再来(一个|一条|一段)?|换一个|还有(吗|呢)?|然后呢?|接着(说|讲)?|继续(讲|说)?|后来呢?|嗯嗯?|是啊)[呀啊吧。！？?!~～ ]*",text.strip()):
        topic=rows[0]["topic"].partition("/")[0]
    answer="汪，我可以讲笑话、讲个小故事，或者陪你聊聊今天的心情。想玩游戏也可以叫我。"
    if topic is None and fallback is not None:
        return fallback
    token="other"
    if topic in TOPICS:
        phrases=TOPICS[topic][1]
        index=0
        if rows and rows[0]["topic"].startswith(topic+"/"):
            index=(int(rows[0]["topic"].partition("/")[2])+1)%len(phrases)
        answer=phrases[index]
        token=f"{topic}/{index}"
    db.execute("INSERT INTO local_turns VALUES(?,?,?,?,?,?)",(event["seq"],*key,event["arrived"],token))
    db.execute("""DELETE FROM local_turns WHERE seq IN
                  (SELECT seq FROM local_turns WHERE grp=? AND member=? AND binding=?
                   ORDER BY seq DESC LIMIT -1 OFFSET 16)""",key)
    return answer
