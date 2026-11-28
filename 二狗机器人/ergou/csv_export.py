"""Generate a bounded-memory CSV from one SQLite read snapshot."""
import csv
import math
from tempfile import TemporaryFile

from . import admin, reports

TIME_FIELDS = {"群消息接收记录":"arrived","运行告警":"opened","会话":"started",
               "积分流水":"at","发送任务":"created","入站异常":"arrived","定时通知":"due",
               "审计":"at","撤回记录":"at"}
PRIVATE = {"成员昵称","成员","发送成员ID","来源消息ID","发起人","操作人","说明","原因","内容","结果","跟踪号","结局"}


def boundary(params, key):
    if key not in params:
        return None
    value = float(params[key][0])
    if not math.isfinite(value):
        raise ValueError("时间边界无效")
    return value


def rows(db,user,group,name,params,*,offset=None):
    admin.permitted(user,group)
    if name in ("后台权限","撤回记录") and user["role"]!="系统管理员":
        raise PermissionError("仅系统管理员可导出")
    start,end = boundary(params,"start"),boundary(params,"end")
    if start is not None and end is not None and start>=end:
        raise ValueError("开始时间应早于结束时间")
    if name=="周报归档":
        return reports.archive_rows(db,group,limit=-1 if offset is None else 200,offset=offset or 0,start=start,end=end)
    query = admin.VIEWS.get(name)
    args=[group]
    if name=="玩家渔获" and params.get("member",[""])[0]:
        member=params["member"][0].strip()
        if not member or len(member)>256:
            raise ValueError("成员 ID 无效")
        before,order=query.rsplit(" ORDER BY ",1)
        query=before+" AND p.member=? ORDER BY "+order
        args.append(member)
    if start is not None or end is not None:
        field=TIME_FIELDS.get(name)
        if not field:
            raise ValueError("此视图不支持时间筛选")
        before,order=query.rsplit(" ORDER BY ",1)
        for operator,value in ((">=",start),("<",end)):
            if value is not None:
                before+=f" AND {field}{operator}?"
                args.append(value)
        query=before+" ORDER BY "+order
    if query:
        if offset is not None:
            query+=" LIMIT 200 OFFSET ?"
            args.append(offset)
        return map(dict,db.execute(query,args))
    return admin.view(db,user,group,name)


def prepare(db,user,group,name,params):
    output=TemporaryFile(mode="w+",encoding="utf-8",newline="")
    try:
        db.execute("BEGIN")
        output.write("\ufeff")
        writer=csv.writer(output)
        for index,row in enumerate(rows(db,user,group,name,params)):
            if index==0:
                writer.writerow(row.keys())
            values=[]
            for key,value in row.items():
                if user["role"]!="系统管理员" and key in PRIVATE:
                    value="已隐藏"
                if isinstance(value,str) and (value.startswith(("\t","\r","\n")) or value.lstrip().startswith(("=","+","-","@"))):
                    value="'"+value
                values.append(value)
            writer.writerow(values)
        db.commit()
        output.flush()
        output.seek(0)
        return output
    except BaseException:
        db.rollback()
        output.close()
        raise
