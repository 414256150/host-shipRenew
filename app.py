#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
from seleniumbase import SB


# ============================================================
# 环境变量
# ============================================================

EMAIL        = os.environ.get("HOSTSHIP_EMAIL") or ""
PASSWORD     = os.environ.get("HOSTSHIP_PASSWORD") or ""
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

BASE_URL = "https://panel.host-ship.com"


# ============================================================
# Telegram 推送
# ============================================================

def send_tg_message(status_icon, status_text, extra=""):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过 Telegram 推送。")
        return

    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)

        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = EMAIL[:2] + '****'

    text = (
        f"🚢 Host Ship 续期通知\n\n"
        f"{status_icon} {status_text}\n"
        f"👤 账户: {masked_email}\n"
        f"⏱️ 时间: {current_time_str}"
    )

    if extra:
        text += f"\n📋 详情: {extra}"

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text
            },
            timeout=10
        )

        if r.status_code == 200:
            print("📩 Telegram 通知发送成功！")
        else:
            print(f"⚠️ Telegram 通知发送失败: {r.text}")

    except Exception as e:
        print(f"⚠️ Telegram 通知发送异常: {e}")


# ============================================================
# Cloudflare Turnstile 页面注入脚本
# ============================================================

_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');

    if (!ts) {
        return 'no-turnstile';
    }

    var el = ts;

    for (var i = 0; i < 20; i++) {
        el = el.parentElement;

        if (!el) {
            break;
        }

        var s = window.getComputedStyle(el);

        if (
            s.overflow === 'hidden' ||
            s.overflowX === 'hidden' ||
            s.overflowY === 'hidden'
        ) {
            el.style.overflow = 'visible';
        }

        el.style.minWidth = 'max-content';
    }

    document.querySelectorAll('iframe').forEach(function(f) {
        if (
            f.src &&
            f.src.includes('challenges.cloudflare.com')
        ) {
            f.style.width = '300px';
            f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible';
            f.style.opacity = '1';
        }
    });

    return 'done';
})()
"""


_EXISTS_JS = """
(function() {
    return document.querySelector(
        'input[name="cf-turnstile-response"]'
    ) !== null;
})()
"""


_SOLVED_JS = """
(function() {
    var i = document.querySelector(
        'input[name="cf-turnstile-response"]'
    );

    return !!(
        i &&
        i.value &&
        i.value.length > 20
    );
})()
"""


# ============================================================
# DOM 检查
# ============================================================

_FORM_INFO_JS = """
(function() {

    function info(selector) {
        var nodes = document.querySelectorAll(selector);

        var result = [];

        for (var i = 0; i < nodes.length; i++) {
            var el = nodes[i];
            var rect = el.getBoundingClientRect();

            result.push({
                tag: el.tagName,
                type: el.type || "",
                name: el.name || "",
                id: el.id || "",
                valueLength: (el.value || "").length,
                disabled: !!el.disabled,
                readonly: !!el.readOnly,
                display: window.getComputedStyle(el).display,
                visibility: window.getComputedStyle(el).visibility,
                opacity: window.getComputedStyle(el).opacity,
                width: rect.width,
                height: rect.height,
                x: rect.x,
                y: rect.y
            });
        }

        return result;
    }

    return {
        email: info(
            'input[type="email"], input[name="email"]'
        ),

        password: info(
            'input[type="password"], input[name="password"]'
        ),

        submit: info(
            'button[type="submit"], input[type="submit"]'
        )
    };

})()
"""


# ============================================================
# JS 填充输入框
# ============================================================

def js_fill_input(sb, selector: str, text: str):
    """
    使用原生 HTMLInputElement.value setter 填充输入框。

    这样可以兼容 React / Vue / Alpine 等前端框架，
    避免单纯 execute_script 设置 value 后页面没有感知。
    """

    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )

    result = sb.execute_script(
        f"""
        (function() {{

            var selectors = "{selector}".split(",");

            var el = null;

            for (var i = 0; i < selectors.length; i++) {{
                var s = selectors[i].trim();
                el = document.querySelector(s);

                if (el) {{
                    break;
                }}
            }}

            if (!el) {{
                return {{
                    ok: false,
                    reason: "element-not-found"
                }};
            }}

            try {{
                el.scrollIntoView({{
                    behavior: "instant",
                    block: "center"
                }});
            }} catch (e) {{}}

            try {{
                el.focus();
            }} catch (e) {{}}

            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                "value"
            );

            if (setter && setter.set) {{
                setter.set.call(el, "{safe_text}");
            }} else {{
                el.value = "{safe_text}";
            }}

            el.dispatchEvent(
                new Event("input", {{
                    bubbles: true
                }})
            );

            el.dispatchEvent(
                new Event("change", {{
                    bubbles: true
                }})
            );

            el.dispatchEvent(
                new Event("blur", {{
                    bubbles: true
                }})
            );

            return {{
                ok: true,
                valueLength: (el.value || "").length,
                type: el.type || "",
                name: el.name || ""
            }};

        }})()
        """
    )

    return result


# ============================================================
# 登录表单 DOM 检查
# ============================================================

def inspect_login_form(sb):
    """
    直接检查当前 document DOM。

    这里故意不使用 wait_for_element()，
    因为当前问题就是源码里存在 input，
    但 SeleniumBase 的可见元素等待失败。
    """

    try:
        info = sb.execute_script(_FORM_INFO_JS)

        if not isinstance(info, dict):
            print("⚠️ 无法读取登录表单 DOM")
            return False

        emails = info.get("email") or []
        passwords = info.get("password") or []
        submits = info.get("submit") or []

        print(
            f"🔎 DOM 检查: "
            f"email={len(emails)}, "
            f"password={len(passwords)}, "
            f"submit={len(submits)}"
        )

        if emails:
            e = emails[0]

            print(
                "  📧 email: "
                f"type={e.get('type')}, "
                f"name={e.get('name')}, "
                f"display={e.get('display')}, "
                f"visibility={e.get('visibility')}, "
                f"size={e.get('width')}x{e.get('height')}"
            )

        if passwords:
            p = passwords[0]

            print(
                "  🔑 password: "
                f"type={p.get('type')}, "
                f"name={p.get('name')}, "
                f"display={p.get('display')}, "
                f"visibility={p.get('visibility')}, "
                f"size={p.get('width')}x{p.get('height')}"
            )

        return bool(emails and passwords)

    except Exception as e:
        print(f"⚠️ DOM 检查异常: {e}")
        return False


# ============================================================
# Turnstile
# ============================================================

def handle_turnstile(sb) -> bool:

    print("🔍 处理 Cloudflare Turnstile 验证...")

    time.sleep(2)

    # --------------------------------------------------------
    # 先检查是否已经静默通过
    # --------------------------------------------------------

    try:
        if sb.execute_script(_SOLVED_JS):
            print("✅ Turnstile 已静默通过")
            return True
    except Exception:
        pass

    # --------------------------------------------------------
    # 尝试展开 Turnstile
    # --------------------------------------------------------

    for _ in range(3):
        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass

        time.sleep(0.5)

    # --------------------------------------------------------
    # SeleniumBase UC CAPTCHA 处理
    # --------------------------------------------------------

    for attempt in range(6):

        try:
            if sb.execute_script(_SOLVED_JS):
                print(
                    f"✅ Turnstile 通过"
                    f"（第 {attempt} 次检查）"
                )
                return True
        except Exception:
            pass

        print(
            f"🖱️ 第 {attempt + 1} 次调用 "
            f"uc_gui_click_captcha..."
        )

        try:
            sb.uc_gui_click_captcha()

        except Exception as e:
            print(
                f"⚠️ uc_gui_click_captcha 调用异常: {e}"
            )

        # 最多等待 8 秒
        for _ in range(16):

            time.sleep(0.5)

            try:
                if sb.execute_script(_SOLVED_JS):
                    print(
                        f"✅ Turnstile 通过"
                        f"（第 {attempt + 1} 次尝试）"
                    )
                    return True
            except Exception:
                pass

        print(
            f"⚠️ 第 {attempt + 1} 次未通过，重试..."
        )

    print("❌ Turnstile 6 次均失败")

    return False


# ============================================================
# 登录
# ============================================================

def login(sb) -> bool:

    login_url = BASE_URL + "/auth/login"

    print()
    print("=" * 60)
    print("🔐 开始 Host Ship 登录")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. 打开登录页面
    # --------------------------------------------------------

    print(f"🌐 打开登录页面: {login_url}")

    try:
        sb.uc_open_with_reconnect(
            login_url,
            reconnect_time=8
        )

    except Exception as e:
        print(f"⚠️ uc_open_with_reconnect 异常: {e}")

        try:
            sb.open(login_url)
        except Exception as e2:
            print(f"❌ 普通打开页面也失败: {e2}")
            return False

    # 给 Cloudflare / JS 一点启动时间
    time.sleep(5)

    # --------------------------------------------------------
    # 2. 等待页面返回登录 HTML
    #
    # 注意：
    # 这里只判断源码，不再把源码检测当成元素可见。
    # --------------------------------------------------------

    print("⏳ 等待登录页面 / Cloudflare...")

    source_ready = False

    for i in range(30):

        try:
            page_src = (
                sb.get_page_source() or ""
            ).lower()

            if (
                'type="email"' in page_src
                or 'name="email"' in page_src
                or 'type="password"' in page_src
            ):
                source_ready = True

                print(
                    f"✅ 登录页面 HTML 已返回"
                    f"（{i + 1}s）"
                )

                break

        except Exception:
            pass

        time.sleep(1)

    if not source_ready:
        print(
            "⚠️ 30 秒内没有检测到登录表单 HTML"
        )

    # --------------------------------------------------------
    # 3. 关键修改：
    #
    # 不再使用：
    #
    # sb.wait_for_element(...)
    #
    # 改成直接检查 DOM。
    # --------------------------------------------------------

    print("🔎 等待登录表单进入 DOM...")

    form_ready = False

    for i in range(20):

        if inspect_login_form(sb):
            form_ready = True

            print(
                f"✅ 登录表单 DOM 已确认"
                f"（第 {i + 1} 次检查）"
            )

            break

        time.sleep(1)

    # --------------------------------------------------------
    # 4. 如果仍然没有 DOM 表单
    # --------------------------------------------------------

    if not form_ready:

        print("❌ 页面未加载出完整登录表单")

        try:
            print(
                f"  当前 URL: "
                f"{sb.get_current_url()}"
            )

            print(
                f"  当前标题: "
                f"{sb.get_title()}"
            )

        except Exception:
            pass

        # 再打印一次 DOM 信息
        try:
            info = sb.execute_script(
                _FORM_INFO_JS
            )
            print(f"  DOM 调试信息: {info}")
        except Exception:
            pass

        # 保存截图
        try:
            sb.save_screenshot(
                "login_form_fail.png"
            )
        except Exception:
            pass

        # 保存页面源码
        try:
            with open(
                "login_form_fail.html",
                "w",
                encoding="utf-8"
            ) as f:
                f.write(
                    sb.get_page_source() or ""
                )

            print(
                "📄 已保存 login_form_fail.html"
            )

        except Exception as e:
            print(
                f"⚠️ 保存页面源码失败: {e}"
            )

        return False

    # --------------------------------------------------------
    # 5. Cookie 弹窗
    # --------------------------------------------------------

    print("🍪 检查 Cookie 弹窗...")

    try:

        for btn in sb.find_elements("button"):

            txt = (
                btn.text or ""
            ).strip().lower()

            if any(
                k in txt
                for k in [
                    "accept",
                    "agree",
                    "cookie",
                    "同意",
                    "接受"
                ]
            ):

                try:
                    btn.click()

                    print(
                        f"✅ 已关闭 Cookie 弹窗: "
                        f"{btn.text}"
                    )

                    time.sleep(0.5)

                except Exception:
                    pass

                break

    except Exception:
        pass

    # --------------------------------------------------------
    # 6. 填写邮箱
    # --------------------------------------------------------

    print("📧 填写邮箱...")

    email_result = None

    try:

        email_result = js_fill_input(
            sb,
            'input[type="email"], input[name="email"]',
            EMAIL
        )

        print(
            f"  JS 填充结果: {email_result}"
        )

    except Exception as e:

        print(
            f"⚠️ JS 填写邮箱异常: {e}"
        )

    time.sleep(1)

    # 验证邮箱是否真的写进去
    try:

        email_value_len = sb.execute_script(
            """
            (function() {
                var el =
                    document.querySelector(
                        'input[type="email"]'
                    ) ||
                    document.querySelector(
                        'input[name="email"]'
                    );

                return el
                    ? (el.value || "").length
                    : -1;
            })()
            """
        )

        print(
            f"📧 邮箱输入框当前长度: "
            f"{email_value_len}"
        )

        if email_value_len <= 0:
            print(
                "⚠️ 邮箱没有成功写入，"
                "尝试 SeleniumBase 直接输入..."
            )

            try:
                sb.wait_for_element_present(
                    'input[type="email"], input[name="email"]',
                    timeout=5
                )

                sb.type(
                    'input[type="email"], input[name="email"]',
                    EMAIL,
                    clear=True
                )

            except Exception as e:
                print(
                    f"⚠️ SeleniumBase 填写邮箱失败: {e}"
                )

    except Exception as e:

        print(
            f"⚠️ 检查邮箱输入值失败: {e}"
        )

    # --------------------------------------------------------
    # 7. 填写密码
    # --------------------------------------------------------

    print("🔑 填写密码...")

    password_result = None

    try:

        password_result = js_fill_input(
            sb,
            'input[type="password"], input[name="password"]',
            PASSWORD
        )

        print(
            f"  JS 填充结果: {password_result}"
        )

    except Exception as e:

        print(
            f"⚠️ JS 填写密码异常: {e}"
        )

    time.sleep(2)

    # 验证密码是否真的写进去
    try:

        password_value_len = sb.execute_script(
            """
            (function() {
                var el =
                    document.querySelector(
                        'input[type="password"]'
                    ) ||
                    document.querySelector(
                        'input[name="password"]'
                    );

                return el
                    ? (el.value || "").length
                    : -1;
            })()
            """
        )

        print(
            f"🔑 密码输入框当前长度: "
            f"{password_value_len}"
        )

        if password_value_len <= 0:

            print(
                "⚠️ 密码没有成功写入，"
                "尝试 SeleniumBase 直接输入..."
            )

            try:

                sb.wait_for_element_present(
                    'input[type="password"], input[name="password"]',
                    timeout=5
                )

                sb.type(
                    'input[type="password"], input[name="password"]',
                    PASSWORD,
                    clear=True
                )

            except Exception as e:

                print(
                    f"⚠️ SeleniumBase 填写密码失败: {e}"
                )

    except Exception as e:

        print(
            f"⚠️ 检查密码输入值失败: {e}"
        )

    # --------------------------------------------------------
    # 8. 等待 Turnstile
    # --------------------------------------------------------

    print("⏳ 等待 Turnstile...")

    ts_found = False

    for i in range(10):

        try:

            if sb.execute_script(_EXISTS_JS):

                ts_found = True

                print(
                    f"✅ 检测到 Turnstile"
                    f"（{i + 1}s）"
                )

                break

        except Exception:
            pass

        time.sleep(1)

    if ts_found:

        if not handle_turnstile(sb):

            print(
                "❌ 登录界面的 Turnstile 验证失败"
            )

            try:
                sb.save_screenshot(
                    "login_turnstile_fail.png"
                )
            except Exception:
                pass

            return False

    else:

        print(
            "ℹ️ 未检测到 Turnstile"
        )

    # --------------------------------------------------------
    # 9. 提交登录
    #
    # 参照 KataBump：
    # 优先对 password 输入框发送 Enter。
    #
    # Host Ship 当前版本也优先采用这种方式，
    # 避免误点击页面其他 button。
    # --------------------------------------------------------

    print("🖱️ 提交登录...")

    submitted = False

    # 第一方案：密码框 Enter
    try:

        sb.wait_for_element_present(
            'input[type="password"], input[name="password"]',
            timeout=5
        )

        sb.press_keys(
            'input[type="password"], input[name="password"]',
            "\n"
        )

        submitted = True

        print(
            "✅ 已通过密码框 Enter 提交"
        )

    except Exception as e:

        print(
            f"⚠️ Enter 提交失败: {e}"
        )

    # --------------------------------------------------------
    # 10. 如果 Enter 没提交，寻找真实 submit 按钮
    # --------------------------------------------------------

    if not submitted:

        print(
            "🔎 尝试查找 Login / Sign in 提交按钮..."
        )

        try:

            buttons = sb.find_elements(
                'button[type="submit"], input[type="submit"], button'
            )

            submit = None

            for btn in buttons:

                txt = (
                    btn.text or ""
                ).strip().lower()

                aria = (
                    btn.get_attribute("aria-label")
                    or ""
                ).strip().lower()

                value = (
                    btn.get_attribute("value")
                    or ""
                ).strip().lower()

                combined = (
                    f"{txt} {aria} {value}"
                )

                if any(
                    k in combined
                    for k in [
                        "login",
                        "sign in",
                        "signin",
                        "登录"
                    ]
                ):

                    submit = btn
                    break

            if submit:

                try:

                    sb.execute_script(
                        """
                        arguments[0]
                            .scrollIntoView({
                                block: 'center'
                            });
                        """,
                        submit
                    )

                    time.sleep(0.5)

                    submit.click()

                    submitted = True

                    print(
                        f"✅ 已点击登录按钮: "
                        f"{submit.text}"
                    )

                except Exception as e:

                    print(
                        f"⚠️ 点击登录按钮失败: {e}"
                    )

        except Exception as e:

            print(
                f"⚠️ 查找登录按钮异常: {e}"
            )

    if not submitted:

        print(
            "❌ 无法提交登录表单"
        )

        try:
            sb.save_screenshot(
                "login_submit_fail.png"
            )
        except Exception:
            pass

        return False

    # --------------------------------------------------------
    # 11. 等待登录结果
    # --------------------------------------------------------

    print("⏳ 等待登录跳转...")

    login_success = False

    for i in range(20):

        time.sleep(1)

        try:

            cur_url = (
                sb.get_current_url()
                .split("?", 1)[0]
                .lower()
            )

            title = (
                sb.get_title() or ""
            ).lower()

            page = (
                sb.get_page_source() or ""
            ).lower()

            # URL 特征
            if "/auth/login" not in cur_url:

                # 常见登录成功页面
                if any(
                    x in cur_url
                    for x in [
                        "/dashboard",
                        "/server/",
                        "/servers/",
                        "/account",
                        "/profile"
                    ]
                ):

                    login_success = True

                # 有些站点跳转 URL 不明显，
                # 通过页面特征判断
                elif any(
                    x in page
                    for x in [
                        "logout",
                        "log out",
                        "sign out",
                        "dashboard",
                        "manage server"
                    ]
                ):

                    login_success = True

            if login_success:

                print(
                    f"✅ 登录成功！"
                    f"（第 {i + 1}s）"
                )

                print(
                    f"   URL: {sb.get_current_url()}"
                )

                print(
                    f"   Title: {sb.get_title()}"
                )

                break

        except Exception:
            pass

    # --------------------------------------------------------
    # 12. 最终判断
    # --------------------------------------------------------

    try:

        final_url = sb.get_current_url()
        final_title = sb.get_title() or ""
        final_page = (
            sb.get_page_source() or ""
        ).lower()

    except Exception:

        final_url = ""
        final_title = ""
        final_page = ""

    if login_success:

        print(
            f"✅ Host Ship 登录成功"
        )

        print(
            f"   当前 URL: {final_url}"
        )

        print(
            f"   当前标题: {final_title}"
        )

        return True

    # 最后一次判断：
    # 只要已经离开 /auth/login，
    # 就认为登录流程成功。
    if "/auth/login" not in final_url.lower():

        print(
            f"✅ 登录页面已离开，"
            f"视为登录成功"
        )

        print(
            f"   当前 URL: {final_url}"
        )

        return True

    # 登录失败
    print()
    print("❌ Host Ship 登录失败")

    print(
        f"   当前 URL: {final_url}"
    )

    print(
        f"   当前标题: {final_title}"
    )

    # 保存失败截图
    try:
        sb.save_screenshot(
            "login_failed.png"
        )
    except Exception:
        pass

    # 保存源码
    try:

        with open(
            "login_failed.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(
                sb.get_page_source() or ""
            )

        print(
            "📄 已保存 login_failed.html"
        )

    except Exception:
        pass

    return False


# ============================================================
# 进入服务器管理页面
# ============================================================

def go_to_server(sb) -> bool:

    print("🖥️ 确保在 Dashboard 页面...")

    cur = sb.get_current_url().lower()

    if "/server/" not in cur:

        sb.open(BASE_URL)

        time.sleep(5)

    print(
        "🔍 在 Dashboard 查找服务器并进入管理页..."
    )

    time.sleep(3)

    # --------------------------------------------------------
    # 优先找 MANAGE SERVER
    # --------------------------------------------------------

    manage_btn = None

    try:

        for el in sb.find_elements("button, a"):

            txt = (
                el.text or ""
            ).strip().upper()

            if (
                "MANAGE SERVER" in txt
                or "管理服务器" in txt
            ):

                manage_btn = el

                print(
                    f"✅ 找到按钮: "
                    f"[{el.text.strip()}]"
                )

                break

    except Exception:
        pass

    if manage_btn:

        try:

            sb.execute_script(
                """
                arguments[0].scrollIntoView({
                    block: 'center'
                });
                """,
                manage_btn
            )

            time.sleep(0.5)

            manage_btn.click()

            time.sleep(5)

            print(
                f"📄 已进入服务器页面: "
                f"{sb.get_current_url()}"
            )

            return True

        except Exception as e:

            print(
                f"点击 MANAGE SERVER 失败: {e}"
            )

    # --------------------------------------------------------
    # 备选：/server/ 链接
    # --------------------------------------------------------

    try:

        for a in sb.find_elements("a"):

            href = (
                a.get_attribute("href")
                or ""
            ).lower()

            if (
                "/server/" in href
                and "create" not in href
            ):

                print(
                    f"✅ 找到服务器链接: {href}"
                )

                a.click()

                time.sleep(5)

                print(
                    f"📄 已进入服务器页面: "
                    f"{sb.get_current_url()}"
                )

                return True

    except Exception as e:

        print(
            f"查找服务器链接异常: {e}"
        )

    # --------------------------------------------------------
    # 再备选：服务器名称区域
    # --------------------------------------------------------

    try:

        for el in sb.find_elements(
            "div, span, h1, h2, h3"
        ):

            txt = (
                el.text or ""
            ).lower()

            if (
                "server" in txt
                and (
                    "online" in txt
                    or "#" in txt
                )
            ):

                el.click()

                time.sleep(5)

                if (
                    "/server/"
                    in sb.get_current_url().lower()
                ):

                    print(
                        f"📄 已进入服务器页面: "
                        f"{sb.get_current_url()}"
                    )

                    return True

    except Exception:
        pass

    print(
        "❌ 未能进入服务器管理页面"
    )

    sb.save_screenshot(
        "go_to_server_fail.png"
    )

    return False


# ============================================================
# 续期
# ============================================================

def do_renew(sb):

    print("\n" + "#" * 30)
    print("  开始 Host Ship 续期流程")
    print("#" * 30)

    if not go_to_server(sb):

        send_tg_message(
            "❌",
            "进入服务器页面失败"
        )

        return

    time.sleep(3)

    # --------------------------------------------------------
    # 查找续期按钮
    # --------------------------------------------------------

    print("🔄 查找续期按钮...")

    renew_btn = None
    candidates = []

    try:

        for el in sb.find_elements(
            "button, a, div[role='button']"
        ):

            txt = (
                el.text or ""
            ).strip().lower()

            if not txt:
                continue

            if any(
                k in txt
                for k in [
                    "renew",
                    "续期",
                    "renewal",
                    "extend"
                ]
            ):

                candidates.append(
                    (el, txt)
                )

                print(
                    f"  找到候选按钮: [{txt}]"
                )

    except Exception as e:

        print(
            f"查找按钮异常: {e}"
        )

    # --------------------------------------------------------
    # 判断按钮
    # --------------------------------------------------------

    for el, txt in candidates:

        if (
            "limit reached" in txt
            or "已达上限" in txt
            or "无法续期" in txt
        ):

            print(
                f"ℹ️ 当前显示「{txt}」，"
                f"可能未到续期窗口"
            )

            send_tg_message(
                "⏳",
                "未到续期时间 / 已达上限",
                txt
            )

            sb.save_screenshot(
                "renew_limit.png"
            )

            return

        if (
            "renew" in txt
            or "续期" in txt
        ):

            renew_btn = el

            break

    if not renew_btn and candidates:
        renew_btn = candidates[0][0]

    if not renew_btn:

        print(
            "❌ 未找到任何续期相关按钮"
        )

        try:

            page = (
                sb.get_page_source()
                or ""
            )

            if (
                "renewal" in page.lower()
                or "renew" in page.lower()
            ):

                print(
                    "页面源码中包含 renew 关键字，"
                    "可能是按钮文本变化"
                )

        except Exception:
            pass

        sb.save_screenshot(
            "no_renew_btn.png"
        )

        send_tg_message(
            "❌",
            "未找到续期按钮"
        )

        return

    # --------------------------------------------------------
    # 点击续期
    # --------------------------------------------------------

    print(
        f"🖱️ 点击续期按钮: "
        f"{(renew_btn.text or '').strip()}"
    )

    try:

        sb.execute_script(
            """
            arguments[0].scrollIntoView({
                block: 'center'
            });
            """,
            renew_btn
        )

        time.sleep(0.5)

        renew_btn.click()

    except Exception:

        sb.execute_script(
            "arguments[0].click();",
            renew_btn
        )

    time.sleep(5)

    # --------------------------------------------------------
    # 确认弹窗
    # --------------------------------------------------------

    print(
        "⏳ 检查是否有确认弹窗或验证..."
    )

    try:

        for btn in sb.find_elements("button"):

            t = (
                btn.text or ""
            ).lower()

            if any(
                k in t
                for k in [
                    "confirm",
                    "yes",
                    "ok",
                    "renew",
                    "确认",
                    "续期"
                ]
            ):

                print(
                    f"🖱️ 点击确认: {btn.text}"
                )

                btn.click()

                time.sleep(3)

                break

    except Exception:
        pass

    # --------------------------------------------------------
    # 再次检查 Turnstile
    # --------------------------------------------------------

    try:

        if sb.execute_script(_EXISTS_JS):

            print(
                "检测到续期页 Turnstile，"
                "尝试处理..."
            )

            handle_turnstile(sb)

            time.sleep(2)

            try:

                for btn in sb.find_elements(
                    "button"
                ):

                    if (
                        "renew"
                        in (btn.text or "").lower()
                    ):

                        btn.click()

                        break

            except Exception:
                pass

    except Exception:
        pass

    time.sleep(6)

    # --------------------------------------------------------
    # 判断续期结果
    # --------------------------------------------------------

    page = (
        sb.get_page_source()
        or ""
    ).lower()

    cur_url = sb.get_current_url()

    if any(
        k in page
        for k in [
            "success",
            "renewed",
            "extended",
            "成功",
            "已续期"
        ]
    ):

        print("✅ 续期成功！")

        send_tg_message(
            "✅",
            "续期成功"
        )

    elif (
        "limit reached" in page
        or "无法续期" in page
        or "not eligible" in page
    ):

        print(
            "⏳ 未到续期窗口或已达上限"
        )

        send_tg_message(
            "⏳",
            "未到续期时间 / 已达上限"
        )

    else:

        print(
            "ℹ️ 续期操作已执行，"
            "请人工确认结果"
        )

        send_tg_message(
            "ℹ️",
            "续期操作已执行，请人工确认",
            cur_url
        )

    sb.save_screenshot(
        "renew_result.png"
    )


# ============================================================
# 主入口
# ============================================================

def main():

    print("#" * 30)
    print("   Host Ship 自动登录续期")
    print("#" * 30)

    if not EMAIL or not PASSWORD:

        print(
            "❌ 请设置 "
            "HOSTSHIP_EMAIL 和 "
            "HOSTSHIP_PASSWORD"
        )

        return

    IS_PROXY = (
        os.environ
        .get("IS_PROXY", "false")
        .lower()
        == "true"
    )

    proxy_str = (
        os.environ
        .get("PROXY_SERVER", "")
        .strip()
        or "http://127.0.0.1:1081"
    )

    sb_kwargs = {
        "uc": True,
        "headless": False
    }

    if IS_PROXY:

        print(
            f"🔗 使用代理: {proxy_str}"
        )

        sb_kwargs["proxy"] = proxy_str

    else:

        print(
            "🌐 直连访问"
        )

    print(
        "🚀 启动浏览器..."
    )

    with SB(**sb_kwargs) as sb:

        # ----------------------------------------------------
        # 检查出口 IP
        # ----------------------------------------------------

        try:

            sb.open(
                "https://api.ip.sb/ip"
            )

            print(
                f"📍 当前出口IP: "
                f"{sb.get_text('body')}"
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # 登录
        # ----------------------------------------------------

        if login(sb):

            # 登录成功后续期
            do_renew(sb)

        else:

            print(
                "\n❌ 登录失败，"
                "终止续期。"
            )

            send_tg_message(
                "❌",
                "登录失败"
            )


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    main()
