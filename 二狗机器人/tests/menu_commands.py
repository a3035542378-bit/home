"""按玩家读法提取目录入口或页尾可复制的下一步。"""


def commands(body, prefix="二狗"):
    result = []
    for line in body.splitlines():
        if line.startswith("【"):
            command, end, purpose = line[1:].partition("】")
            assert end and command and purpose, line
            line = command if command.startswith("@") else prefix + command
        elif not line.startswith(prefix):
            continue
        if line not in result:
            result.append(line)
    return result
