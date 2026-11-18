"use strict";

function showReplyRules(panel, group, state, api) {
  let version = state.version;
  const form = document.createElement("form");
  const list = document.createElement("div");
  const statusLine = document.createElement("p");
  statusLine.setAttribute("role", "status");

  function button(text, click) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "quiet";
    node.textContent = text;
    node.onclick = click;
    return node;
  }

  function label(caption, control) {
    const node = document.createElement("label");
    node.append(caption, control);
    return node;
  }

  function select(name, options, value) {
    const node = document.createElement("select");
    node.name = name;
    for (const [id, caption] of Object.entries(options)) node.add(new Option(caption, id));
    node.value = value;
    return node;
  }

  function refreshOrder() {
    [...list.children].forEach((row, index) => {
      row.querySelector('[data-move="up"]').disabled = index === 0;
      row.querySelector('[data-move="down"]').disabled = index === list.children.length - 1;
      row.querySelector("h3").textContent = "优先级 " + (index + 1);
    });
    add.disabled = list.children.length >= 64;
  }

  let dragged;
  function appendRule(rule) {
    const row = document.createElement("article");
    const title = document.createElement("h3");
    const keyword = document.createElement("input");
    keyword.name = "keyword";
    keyword.required = true;
    keyword.maxLength = 80;
    keyword.value = rule.keyword;
    const mode = select("mode", {exact: "完全匹配", contains: "包含关键词", similar: "相似度匹配"}, rule.mode);
    const threshold = document.createElement("input");
    threshold.name = "threshold";
    threshold.type = "number";
    threshold.min = "0.1";
    threshold.max = "1";
    threshold.step = "any";
    threshold.required = true;
    threshold.value = rule.threshold;
    const similarity = label("相似度阈值（0.1 至 1）", threshold);
    function updateMode() {
      similarity.hidden = mode.value !== "similar";
      threshold.disabled = similarity.hidden;
    }
    mode.onchange = updateMode;
    updateMode();
    const kind = select("kind", {text: "文字", link: "链接", image: "图片"}, rule.kind);
    const content = document.createElement("textarea");
    content.name = "content";
    content.maxLength = 1200;
    content.required = true;
    content.value = rule.content;
    const preview = document.createElement("output");
    const picture = document.createElement("div");
    const view = button("加载图片预览", () => {
      let source;
      try { source = new URL(content.value.trim()); } catch { return; }
      if (source.protocol !== "https:" || source.username || source.password) return;
      const image = document.createElement("img");
      image.alt = "自定义回复图片预览";
      image.width = 240;
      image.referrerPolicy = "no-referrer";
      image.onerror = () => { if (picture.contains(image)) picture.textContent = "图片未能加载，请检查原图链接。"; };
      picture.replaceChildren(image);
      image.src = source.href;
    });
    function updatePreview() {
      content.placeholder = kind.value === "text" ? "填写要回复的文字" : "https://…";
      preview.textContent = content.value.trim() ? "群内预览 · " + (kind.value === "image" ? "图片：" : "") + content.value.trim() : "";
      picture.replaceChildren();
      view.hidden = kind.value !== "image";
      let url;
      try { url = new URL(content.value.trim()); } catch { /* incomplete address */ }
      view.disabled = !url || url.protocol !== "https:" || Boolean(url.username || url.password);
    }
    content.oninput = updatePreview;
    kind.onchange = updatePreview;
    updatePreview();
    const grid = document.createElement("div");
    grid.className = "grid";
    grid.append(label("触发词", keyword), label("匹配方式", mode), similarity, label("回复类型", kind));
    const actions = document.createElement("div");
    actions.className = "actions";
    const up = button("上移", () => {
      if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
      refreshOrder();
    });
    const down = button("下移", () => {
      if (row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
      refreshOrder();
    });
    up.dataset.move = "up";
    down.dataset.move = "down";
    const handle = document.createElement("span");
    handle.textContent = "拖动排序";
    handle.draggable = true;
    handle.addEventListener("dragstart", event => {
      dragged = row;
      event.dataTransfer.setData("text/plain", "reply-rule");
      event.dataTransfer.effectAllowed = "move";
    });
    handle.addEventListener("dragend", () => { dragged = null; });
    row.addEventListener("dragover", event => {
      if (dragged && dragged !== row) event.preventDefault();
    });
    row.addEventListener("drop", event => {
      if (!dragged || dragged === row) return;
      event.preventDefault();
      const rows = [...list.children];
      list.insertBefore(dragged, rows.indexOf(dragged) < rows.indexOf(row) ? row.nextElementSibling : row);
      dragged = null;
      refreshOrder();
    });
    actions.append(handle, up, down, button("移除", () => { row.remove(); refreshOrder(); }));
    row.append(title, grid, label("回复内容", content), preview, view, picture, actions);
    list.append(row);
  }

  const note = document.createElement("p");
  note.textContent = "成员点名二狗后，按顺序使用首条匹配的规则。模拟群支持图片回复；当前真实群以文字链接发送图片。";
  const add = button("添加规则", () => {
    appendRule({keyword: "", mode: "exact", threshold: 0.8, kind: "text", content: ""});
    refreshOrder();
    list.lastElementChild.querySelector("input").focus();
  });
  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "保存本群规则";
  const controls = document.createElement("div");
  controls.className = "actions";
  controls.append(add, save);
  form.append(note, list, controls, statusLine);
  panel.replaceChildren(form);
  for (const rule of state.rules) appendRule(rule);
  refreshOrder();
  form.onsubmit = async event => {
    event.preventDefault();
    if (save.disabled) return;
    const rules = [...list.children].map(row => {
      const value = name => row.querySelector('[name="' + name + '"]').value;
      return {keyword: value("keyword").trim(), mode: value("mode"), threshold: Number(value("threshold")) || 0.8,
              kind: value("kind"), content: value("content").trim()};
    });
    form.inert = true;
    save.disabled = true;
    statusLine.textContent = "正在保存…";
    try {
      const result = await api("api/reply-rules", {group, version, rules});
      version = result.version;
      statusLine.textContent = "本群规则 v" + version + " 已生效。";
    } catch (error) {
      statusLine.textContent = error.message;
    } finally {
      form.inert = false;
      save.disabled = false;
    }
  };
}
