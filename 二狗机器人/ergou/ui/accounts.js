"use strict";

async function renderAdminAccounts(ticket) {
  const panel = $("adminAccounts");
  const state = await api("api/admin-accounts");
  if (ticket !== revision) return;

  const createCard = el("article", ""), form = el("form", "");
  const listCard = el("article", ""), table = el("table", "");
  const notice = el("output", "");
  notice.setAttribute("aria-live", "polite");
  createCard.append(el("h2", "新增后台账号"), form, notice);
  listCard.append(el("h2", "现有账号"), table);
  panel.replaceChildren(createCard, listCard);

  function field(label, node) {
    const wrapper = el("label", label);
    wrapper.append(node);
    form.append(wrapper);
    return node;
  }

  const name = field("账号名", el("input", ""));
  name.required = true;
  name.maxLength = 80;
  name.autocomplete = "off";
  const password = field("登录密码（至少 12 个字符）", el("input", ""));
  password.type = "password";
  password.autocomplete = "new-password";
  password.required = true;
  password.minLength = 12;
  password.maxLength = 1024;
  const role = field("角色", el("select", ""));
  for (const value of state.roles) role.add(new Option(value, value));
  role.value = "运营管理员";

  const scopeBox = el("fieldset", "");
  scopeBox.append(el("legend", "授权群组"));
  const choices = el("div", "");
  choices.className = "checks";
  const groups = new Map(state.groups.map(group => [group.id, group.name]));
  for (const [id, title] of groups) {
    const check = el("input", "");
    check.type = "checkbox";
    check.value = id;
    const label = el("label", "");
    label.className = "check";
    label.append(check, document.createTextNode(title === id ? title : title + "（" + id + "）"));
    choices.append(label);
  }
  scopeBox.append(choices);
  if (!groups.size) scopeBox.append(el("p", "绑定群组后即可为此角色授权。"));
  const globalScope = el("p", "系统管理员可以管理全部群组和后台账号。");
  const submit = el("button", "创建账号");
  submit.type = "submit";
  form.append(scopeBox, globalScope, submit);

  let saving = false;
  function updateScope() {
    const global = role.value === "系统管理员";
    scopeBox.hidden = global;
    globalScope.hidden = !global;
    submit.disabled = saving || (!global && !choices.querySelector("input:checked"));
  }
  role.onchange = updateScope;
  choices.onchange = updateScope;
  updateScope();

  const header = table.createTHead().insertRow();
  for (const title of ["账号名", "角色", "授权群组"]) header.append(el("th", title));
  const body = table.createTBody();
  function showAccounts(accounts) {
    body.replaceChildren();
    for (const account of accounts) {
      const row = body.insertRow();
      row.insertCell().textContent = account.name;
      row.insertCell().textContent = account.role;
      row.insertCell().textContent = account.role === "系统管理员" ? "全部群组" :
        account.scopes.map(id => groups.get(id) || id).join("、") || "暂无授权群组";
    }
  }
  showAccounts(state.accounts);

  form.onsubmit = async event => {
    event.preventDefault();
    if (saving || ticket !== revision) return;
    const scopes = role.value === "系统管理员" ? [] :
      Array.from(choices.querySelectorAll("input:checked"), node => node.value);
    const loginName = name.value.trim();
    saving = true;
    updateScope();
    notice.textContent = "";
    try {
      const updated = await api("api/admin-accounts", {
        name: loginName, password: password.value, role: role.value, scopes
      });
      if (ticket !== revision) return;
      showAccounts(updated.accounts);
      form.reset();
      role.value = "运营管理员";
      notice.textContent = "已创建后台账号 " + loginName;
      name.focus();
    } catch (failure) {
      if (ticket === revision) notice.textContent = failure.message;
    } finally {
      saving = false;
      if (ticket === revision) updateScope();
    }
  };
}
