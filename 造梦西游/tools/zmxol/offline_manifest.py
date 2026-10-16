"""只删除二进制 Android Manifest 的 INTERNET 权限节点，保留其余原字节。"""

import struct


INTERNET = "android.permission.INTERNET"
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
PERMISSION_ELEMENTS = {"uses-permission", "uses-permission-sdk-23", "uses-permission-sdk-m"}
NO_INDEX = 0xFFFFFFFF


class ManifestError(ValueError):
    """Manifest 结构损坏或权限声明无法安全判定。"""


def _chunks(data: bytes):
    if len(data) < 8 or struct.unpack_from("<HHI", data) != (3, 8, len(data)):
        raise ManifestError("Invalid binary XML header or total length")
    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            raise ManifestError("Truncated XML chunk header")
        kind, header_size, size = struct.unpack_from("<HHI", data, offset)
        if header_size < 8 or size < header_size or size % 4 or header_size % 4 or size > len(data) - offset:
            raise ManifestError("Invalid XML chunk length")
        yield offset, kind, header_size, size
        offset += size


def _strings(chunk: bytes, header_size: int) -> list[str]:
    if header_size != 28:
        raise ManifestError("Invalid string pool header")
    count, style_count, flags, start, styles_start = struct.unpack_from("<5I", chunk, 8)
    offsets_end = header_size + 4 * (count + style_count)
    end = styles_start or len(chunk)
    if not offsets_end <= start <= end <= len(chunk) or start % 4 or style_count > count:
        raise ManifestError("Invalid string pool bounds")
    if bool(style_count) != bool(styles_start) or styles_start % 4:
        raise ManifestError("Invalid string pool style bounds")
    utf8 = bool(flags & 0x100)

    def length(position: int, width: int) -> tuple[int, int]:
        if position + width > end:
            raise ManifestError("Truncated string length")
        value = int.from_bytes(chunk[position:position + width], "little")
        position += width
        high_bit = 1 << (width * 8 - 1)
        if value & high_bit:
            if position + width > end:
                raise ManifestError("Truncated extended string length")
            value = ((value & (high_bit - 1)) << (width * 8)) | int.from_bytes(chunk[position:position + width], "little")
            position += width
        return value, position

    result = []
    for index in range(count):
        position = start + struct.unpack_from("<I", chunk, header_size + 4 * index)[0]
        units, position = length(position, 1 if utf8 else 2)
        if utf8:
            size, position = length(position, 1)
        else:
            size = units * 2
        terminator_size = 1 if utf8 else 2
        if size + terminator_size > end - position or chunk[position + size:position + size + terminator_size] != bytes(terminator_size):
            raise ManifestError("Invalid string length or terminator")
        try:
            value = chunk[position:position + size].decode("utf-8" if utf8 else "utf-16-le")
        except UnicodeDecodeError as error:
            raise ManifestError("Invalid string encoding") from error
        if "\0" in value or len(value.encode("utf-16-le")) // 2 != units:
            raise ManifestError("Invalid string character length")
        result.append(value)
    for index in range(style_count):
        offset = struct.unpack_from("<I", chunk, header_size + 4 * (count + index))[0]
        if offset == NO_INDEX:
            continue
        position = styles_start + offset
        while True:
            if position + 12 > len(chunk):
                raise ManifestError("Truncated string style span")
            name, first, last = struct.unpack_from("<III", chunk, position)
            if name == NO_INDEX:
                break
            if name >= count or first > last or last >= len(result[index].encode("utf-16-le")) // 2:
                raise ManifestError("Invalid string style span")
            position += 12
    return result


def remove_internet_permission(data: bytes) -> tuple[bytes, list[dict[str, str]]]:
    strings = None
    resource_ids = []
    seen_resource_map = False
    seen_node = False
    root_seen = False
    elements = []
    namespaces = []
    ranges = []
    removed = []

    def text(index: int, optional: bool = False) -> str | None:
        if optional and index == NO_INDEX:
            return None
        if strings is None or index >= len(strings):
            raise ManifestError("Invalid XML string reference")
        return strings[index]

    def typed_value(position: int) -> str | None:
        size, reserved, kind, value = struct.unpack_from("<HBBI", data, position)
        if size != 8 or reserved:
            raise ManifestError("Invalid XML typed value")
        return text(value) if kind == 3 else None

    for offset, kind, header_size, size in _chunks(data):
        end = offset + size
        if kind == 1:
            if strings is not None or seen_node or seen_resource_map:
                raise ManifestError("Unexpected XML string pool")
            strings = _strings(data[offset:end], header_size)
            continue
        if strings is None:
            raise ManifestError("Missing XML string pool")
        if kind == 0x180:
            if header_size != 8 or seen_resource_map or seen_node or (size - 8) // 4 > len(strings):
                raise ManifestError("Invalid XML resource map")
            resource_ids = list(struct.unpack_from(f"<{(size - 8) // 4}I", data, offset + 8))
            seen_resource_map = True
            continue
        if kind not in (0x100, 0x101, 0x102, 0x103, 0x104) or header_size != 16:
            raise ManifestError("Unsupported XML node header")
        seen_node = True
        text(struct.unpack_from("<I", data, offset + 12)[0], optional=True)
        extension = offset + header_size
        required_size = {0x100: 8, 0x101: 8, 0x102: 20, 0x103: 8, 0x104: 12}[kind]
        if required_size > end - extension:
            raise ManifestError("Truncated XML node")
        if kind in (0x100, 0x101):
            prefix, uri = struct.unpack_from("<II", data, extension)
            namespace = (len(elements), text(prefix, optional=True), text(uri))
            if kind == 0x100:
                namespaces.append(namespace)
            elif not namespaces or namespaces.pop() != namespace:
                raise ManifestError("Unbalanced XML namespace")
        elif kind == 0x102:
            ns, name, attribute_start, attribute_size, count, id_index, class_index, style_index = struct.unpack_from("<II6H", data, extension)
            namespace, name = text(ns, optional=True), text(name)
            if attribute_start < 20 or attribute_start % 4 or attribute_size < 20 or attribute_size % 4 or attribute_start + count * attribute_size > end - extension:
                raise ManifestError("Invalid XML attribute bounds")
            if max(id_index, class_index, style_index) > count:
                raise ManifestError("Invalid XML attribute index")
            if not elements:
                if root_seen or namespace is not None or name != "manifest":
                    raise ManifestError("Expected one manifest root element")
                root_seen = True
            elif elements[-1][3]:
                raise ManifestError("INTERNET permission has child elements")
            is_permission = len(elements) == 1 and name in PERMISSION_ELEMENTS
            permission = None
            attributes = set()
            for index in range(count):
                position = extension + attribute_start + index * attribute_size
                attr_ns, attr_name, raw = struct.unpack_from("<III", data, position)
                attr_namespace, attr_text = text(attr_ns, optional=True), text(attr_name)
                if (attr_namespace, attr_text) in attributes:
                    raise ManifestError("Duplicate XML attribute")
                attributes.add((attr_namespace, attr_text))
                raw_value = text(raw, optional=True)
                value = typed_value(position + 12)
                resource_id = resource_ids[attr_name] if attr_name < len(resource_ids) else 0
                if is_permission and (resource_id == 0x01010003 or (attr_namespace == ANDROID_NAMESPACE and attr_text == "name")):
                    if permission is not None or value is None or (raw_value is not None and raw_value != value):
                        raise ManifestError("Ambiguous or nonliteral permission name")
                    permission = value
            if is_permission and permission is None:
                raise ManifestError("Missing permission name")
            elements.append((namespace, name, offset, is_permission and permission == INTERNET))
        elif kind == 0x103:
            ns, name = struct.unpack_from("<II", data, extension)
            pair = text(ns, optional=True), text(name)
            if not elements or elements[-1][:2] != pair:
                raise ManifestError("Unbalanced XML element")
            _, name, start, remove = elements.pop()
            if remove:
                ranges.append((start, end))
                removed.append({"element": name, "name": INTERNET})
        else:
            text(struct.unpack_from("<I", data, extension)[0])
            # 原包的 CDATA 使用全零的未指定 typedData；属性值仍须完整校验。
            if data[extension + 4:extension + 12] != bytes(8):
                typed_value(extension + 4)
            if not elements:
                raise ManifestError("XML text outside root element")
    if not root_seen or elements or namespaces:
        raise ManifestError("Incomplete XML document")
    if not ranges:
        return data, []
    output = bytearray()
    position = 0
    for start, end in ranges:
        output.extend(data[position:start])
        position = end
    output.extend(data[position:])
    struct.pack_into("<I", output, 4, len(output))
    return bytes(output), removed
