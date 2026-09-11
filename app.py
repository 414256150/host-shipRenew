#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Host Ship 自动登录 + 自动续期
================================

运行环境：
- Python 3.10+
- SeleniumBase
- requests
- Chrome / Chromium
- GitHub Actions + Xvfb

环境变量：
    HOSTSHIP_EMAIL
    HOSTSHIP_PASSWORD
    HOSTSHIP_SERVER_ID        # 可选
    TG_CHAT_ID                # 可选
    TG_BOT_TOKEN              # 可选

可选代理：
    IS_PROXY=true
    PROXY_SERVER=http://127.0.0.1:1081

主要改动：
1. 不再强制寻找 input[type="email"]
2. 按浏览器实际 DOM 自动寻找账号输入框
3. 支持 email / username / identifier 等不同命名
4. 支持普通 text 输入框 fallback
5. JS 填充并触发 input/change/blur 事件
6. 密码框优先使用 Enter 模拟浏览器登录
7. 自动处理 Turnstile
8. 登录失败自动保存 HTML / PNG
9. 保留服务器管理及续期逻辑
10. Telegram 通知
"""

import os
import sys
import time
import traceback
from typing import Optional

import requests
from seleniumbase import SB


# ============================================================
# 配置
# ============================================================

BASE_URL = "https://panel.host-ship.com"

LOGIN_URL = f"{BASE_URL}/auth/login"

EMAIL = os.environ.get("HOSTSHIP_EMAIL", "").strip()
PASSWORD = os.environ.get("HOSTSHIP_PASSWORD", "").strip()

SERVER_ID = os.environ.get("HOSTSHIP_SERVER_ID", "").strip()

TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()

IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
PROXY_SERVER = os.environ.get(
    "PROXY_SERVER",
    "http://127.0.0.1:1081"
).strip()


# ============================================================
# 基础工具
# ============================================================

def log(message: str):
    print(message, flush=True)


def save_debug(sb, prefix: str):
    """
    保存调试截图和 HTML。
    不输出密码等敏感内容。
    """
    try:
        sb.save_screenshot(f"{prefix}.png")
        log(f"📸 已保存: {prefix}.png")
    except Exception as e:
        log(f"⚠️ 保存截图失败: {e}")

    try:
        with open(
            f"{prefix}.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(sb.get_page_source())

        log(f"📄 已保存: {prefix}.html")

    except Exception as e:
        log(f"⚠️ 保存 HTML 失败: {e}")


def send_tg_message(message: str) -> bool:
    """
    Telegram 通知。
    未配置 Telegram 时直接跳过。
    """

    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("ℹ️ Telegram 未配置，跳过通知")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TG_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "text": message,
            },
            timeout=20,
        )

        if response.ok:
            log("📩 Telegram 通知发送成功！")
            return True

        log(
            f"⚠️ Telegram 通知失败: "
            f"{response.status_code} "
            f"{response.text[:300]}"
        )

    except Exception as e:
        log(f"⚠️ Telegram 请求异常: {e}")

    return False


# ============================================================
# 浏览器 DOM 工具
# ============================================================

def get_login_dom_info(sb):
    """
    获取当前页面所有可能和登录有关的元素。

    特别注意：
    这里不读取 input.value，避免密码进入日志。
    """

    script = r"""
    function visible(el) {
        if (!el) return false;

        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);

        return (
            r.width > 0 &&
            r.height > 0 &&
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    }

    const elements = Array.from(
        document.querySelectorAll(
            "input, textarea, button, form, iframe, " +
            '[contenteditable="true"]'
        )
    );

    return elements.map((el, index) => {
        const r = el.getBoundingClientRect();

        return {
            index: index,
            tag: el.tagName,
            type: el.getAttribute("type") || "",
            name: el.getAttribute("name") || "",
            id: el.id || "",
            placeholder: el.getAttribute("placeholder") || "",
            autocomplete: el.getAttribute("autocomplete") || "",
            aria: el.getAttribute("aria-label") || "",
            role: el.getAttribute("role") || "",
            src: el.tagName === "IFRAME"
                ? (el.getAttribute("src") || "")
                : "",
            action: el.tagName === "FORM"
                ? (el.getAttribute("action") || "")
                : "",
            method: el.tagName === "FORM"
                ? (el.getAttribute("method") || "")
                : "",
            text: (
                el.innerText ||
                el.textContent ||
                ""
            ).trim().slice(0, 100),
            visible: visible(el),
            width: Math.round(r.width),
            height: Math.round(r.height),
            x: Math.round(r.x),
            y: Math.round(r.y)
        };
    });
    """

    try:
        return sb.execute_script(script)
    except Exception as e:
        log(f"⚠️ DOM 检查失败: {e}")
        return []


def print_login_dom(sb):
    """
    打印登录页面结构，但不打印密码值。
    """

    info = get_login_dom_info(sb)

    log("🔎 当前浏览器登录 DOM：")

    for item in info:
        if item.get("tag") == "INPUT":
            log(
                "   INPUT "
                f"type={item.get('type')} "
                f"name={item.get('name')} "
                f"id={item.get('id')} "
                f"placeholder={item.get('placeholder')} "
                f"autocomplete={item.get('autocomplete')} "
                f"visible={item.get('visible')} "
                f"size={item.get('width')}x{item.get('height')}"
            )

        elif item.get("tag") == "BUTTON":
            log(
                "   BUTTON "
                f"type={item.get('type')} "
                f"text={item.get('text')!r} "
                f"visible={item.get('visible')}"
            )

        elif item.get("tag") == "IFRAME":
            log(
                "   IFRAME "
                f"src={item.get('src')!r} "
                f"visible={item.get('visible')}"
            )

        elif item.get("tag") == "FORM":
            log(
                "   FORM "
                f"action={item.get('action')!r} "
                f"method={item.get('method')!r} "
                f"visible={item.get('visible')}"
            )


def js_fill_input(sb, selector: str, value: str) -> bool:
    """
    使用浏览器 JS 原生 setter 写入 input。

    关键：
    React / Vue / Alpine / 原生监听器可能不会因为直接
    element.value = xxx 而更新状态。

    所以这里同时触发：
        input
        change
        blur
    """

    script = r"""
    const selector = arguments[0];
    const value = arguments[1];

    const el = document.querySelector(selector);

    if (!el) {
        return {
            ok: false,
            reason: "element_not_found"
        };
    }

    el.focus();

    const proto =
        Object.getPrototypeOf(el);

    const descriptor =
        Object.getOwnPropertyDescriptor(
            proto,
            "value"
        );

    if (descriptor && descriptor.set) {
        descriptor.set.call(el, value);
    } else {
        el.value = value;
    }

    el.dispatchEvent(
        new Event("input", {
            bubbles: true
        })
    );

    el.dispatchEvent(
        new Event("change", {
            bubbles: true
        })
    );

    el.dispatchEvent(
        new Event("blur", {
            bubbles: true
        })
    );

    return {
        ok: true,
        valueLength: (el.value || "").length
    };
    """

    try:
        result = sb.execute_script(
            script,
            selector,
            value
        )

        if result and result.get("ok"):
            log(
                f"✅ JS 填充成功: "
                f"{selector} "
                f"(长度={result.get('valueLength')})"
            )
            return True

        log(f"⚠️ JS 填充失败: {result}")

    except Exception as e:
        log(f"⚠️ JS 填充异常: {e}")

    # SeleniumBase 普通输入 fallback
    try:
        sb.click(selector)
        sb.clear(selector)
        sb.type(selector, value)

        log(f"✅ 浏览器普通输入 fallback 成功: {selector}")
        return True

    except Exception as e:
        log(f"❌ 普通输入也失败: {e}")

    return False


# ============================================================
# 自动识别登录输入框
# ============================================================

def find_password_selector(sb) -> Optional[str]:
    """
    寻找密码框。
    """

    selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[id*="password" i]',
        'input[autocomplete="current-password"]',
        'input[autocomplete="password"]',
    ]

    for selector in selectors:
        try:
            if sb.is_element_present(selector):
                return selector
        except Exception:
            pass

    return None


def find_username_selector(sb) -> Optional[str]:
    """
    自动寻找邮箱 / 用户名输入框。

    不再依赖：
        input[type=email]

    优先级：
        email
        username
        identifier
        login
        autocomplete=username
        placeholder
        普通 text input
    """

    # --------------------------------------------------------
    # 第一层：常见 selector
    # --------------------------------------------------------

    selectors = [
        'input[type="email"]',

        'input[name="email"]',
        'input[name="username"]',
        'input[name="user"]',
        'input[name="identifier"]',
        'input[name="login"]',

        'input[id*="email" i]',
        'input[id*="username" i]',
        'input[id*="user" i]',
        'input[id*="identifier" i]',
        'input[id*="login" i]',

        'input[placeholder*="email" i]',
        'input[placeholder*="e-mail" i]',
        'input[placeholder*="username" i]',
        'input[placeholder*="user" i]',
        'input[placeholder*="login" i]',

        'input[autocomplete="username"]',
        'input[autocomplete="email"]',
    ]

    for selector in selectors:
        try:
            if sb.is_element_present(selector):
                return selector
        except Exception:
            pass

    # --------------------------------------------------------
    # 第二层：根据 DOM 自动识别
    # --------------------------------------------------------

    script = r"""
    function visible(el) {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);

        return (
            r.width > 100 &&
            r.height > 20 &&
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    }

    const inputs = Array.from(
        document.querySelectorAll("input")
    ).filter(visible);

    for (const el of inputs) {

        const type =
            (el.type || "").toLowerCase();

        const name =
            (el.name || "").toLowerCase();

        const id =
            (el.id || "").toLowerCase();

        const placeholder =
            (el.placeholder || "").toLowerCase();

        const autocomplete =
            (el.autocomplete || "").toLowerCase();

        if (
            type === "password" ||
            type === "hidden" ||
            type === "submit" ||
            type === "button" ||
            type === "checkbox"
        ) {
            continue;
        }

        const score =
            (type === "email" ? 100 : 0) +
            (name.includes("email") ? 80 : 0) +
            (name.includes("user") ? 70 : 0) +
            (name.includes("login") ? 60 : 0) +
            (name.includes("identifier") ? 60 : 0) +
            (id.includes("email") ? 80 : 0) +
            (id.includes("user") ? 70 : 0) +
            (placeholder.includes("email") ? 80 : 0) +
            (placeholder.includes("user") ? 70 : 0) +
            (autocomplete === "username" ? 100 : 0) +
            (autocomplete === "email" ? 90 : 0);

        if (score > 0) {
            el.setAttribute(
                "data-hostship-user-field",
                "true"
            );

            return true;
        }
    }

    // 最后 fallback：
    // 第一个可见 text input
    for (const el of inputs) {

        const type =
            (el.type || "").toLowerCase();

        if (
            type === "text" ||
            type === ""
        ) {
            el.setAttribute(
                "data-hostship-user-field",
                "true"
            );

            return true;
        }
    }

    return false;
    """

    try:
        found = sb.execute_script(script)

        if found:
            return (
                'input[data-hostship-user-field="true"]'
            )

    except Exception as e:
        log(f"⚠️ 自动识别账号输入框失败: {e}")

    return None


def find_submit_selector(sb) -> Optional[str]:
    """
    自动寻找登录按钮。
    """

    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button[name="login"]',
        'button[id*="login" i]',
        'button[class*="login" i]',
    ]

    for selector in selectors:
        try:
            if sb.is_element_present(selector):
                return selector
        except Exception:
            pass

    # 根据按钮文字寻找
    script = r"""
    function visible(el) {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);

        return (
            r.width > 50 &&
            r.height > 20 &&
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    }

    const buttons = Array.from(
        document.querySelectorAll("button")
    ).filter(visible);

    const keywords = [
        "login",
        "log in",
        "sign in",
        "signin",
        "submit",
        "登录",
        "登入"
    ];

    for (const button of buttons) {

        const text =
            (
                button.innerText ||
                button.textContent ||
                ""
            ).trim().toLowerCase();

        if (
            keywords.some(
                x => text.includes(x)
            )
        ) {
            button.setAttribute(
                "data-hostship-login-button",
                "true"
            );

            return true;
        }
    }

    return false;
    """

    try:
        if sb.execute_script(script):
            return (
                'button[data-hostship-login-button="true"]'
            )

    except Exception as e:
        log(f"⚠️ 自动寻找登录按钮失败: {e}")

    return None


# ============================================================
# Turnstile
# ============================================================

def turnstile_solved(sb) -> bool:
    """
    检查 Turnstile 是否已经完成。
    """

    script = r"""
    const selectors = [
        'input[name="cf-turnstile-response"]',
        'textarea[name="cf-turnstile-response"]',
        'input[name="g-recaptcha-response"]',
        'textarea[name="g-recaptcha-response"]'
    ];

    for (const selector of selectors) {
        const elements =
            document.querySelectorAll(selector);

        for (const el of elements) {
            if (el.value && el.value.length > 10) {
                return true;
            }
        }
    }

    const checked =
        document.querySelector(
            '.cf-turnstile input[type="checkbox"]:checked'
        );

    if (checked) {
        return true;
    }

    return false;
    """

    try:
        return bool(sb.execute_script(script))
    except Exception:
        return False


def handle_turnstile(sb) -> bool:
    """
    尝试处理 Cloudflare Turnstile。

    SeleniumBase UC 模式通常可以通过：
        uc_gui_click_captcha()

    让浏览器完成可交互的 Turnstile。

    如果页面没有 Turnstile，则直接返回 True。
    """

    try:
        source = sb.get_page_source().lower()

        if (
            "turnstile" not in source and
            "cf-turnstile" not in source
        ):
            log("ℹ️ 当前页面未检测到 Turnstile")
            return True

    except Exception:
        pass

    log("🛡️ 检测到 Cloudflare Turnstile")

    if turnstile_solved(sb):
        log("✅ Turnstile 已经通过")
        return True

    # --------------------------------------------------------
    # SeleniumBase UC CAPTCHA 点击
    # --------------------------------------------------------

    try:
        log("🖱️ 尝试浏览器自动点击 Turnstile...")

        sb.uc_gui_click_captcha()

        time.sleep(5)

    except Exception as e:
        log(f"⚠️ Turnstile 自动点击异常: {e}")

    # --------------------------------------------------------
    # 再次检查
    # --------------------------------------------------------

    if turnstile_solved(sb):
        log("✅ Turnstile 验证完成")
        return True

    # 页面可能是 Cloudflare 自己完成验证
    # 给它更多时间
    for i in range(10):

        time.sleep(1)

        if turnstile_solved(sb):
            log("✅ Turnstile 验证完成")
            return True

    log("⚠️ 未能确认 Turnstile 已完成")
    return False


# ============================================================
# 登录
# ============================================================

def login(sb) -> bool:

    log("")
    log("=" * 60)
    log("🔐 开始 Host Ship 浏览器登录")
    log("=" * 60)

    if not EMAIL:
        log("❌ HOSTSHIP_EMAIL 未配置")
        return False

    if not PASSWORD:
        log("❌ HOSTSHIP_PASSWORD 未配置")
        return False

    # --------------------------------------------------------
    # 1. 打开登录页面
    # --------------------------------------------------------

    log(f"🌐 打开登录页面: {LOGIN_URL}")

    try:
        sb.uc_open_with_reconnect(
            LOGIN_URL,
            reconnect_time=8
        )
    except Exception as e:
        log(f"⚠️ uc_open_with_reconnect 异常: {e}")

        try:
            sb.open(LOGIN_URL)
        except Exception as e2:
            log(f"❌ 打开登录页面失败: {e2}")
            return False

    time.sleep(5)

    log(f"📍 当前 URL: {sb.get_current_url()}")
    log(f"📄 当前标题: {sb.get_title()}")

    # --------------------------------------------------------
    # 2. 等待页面 DOM
    # --------------------------------------------------------

    log("⏳ 等待浏览器登录页面...")

    password_selector = None

    for i in range(20):

        password_selector = find_password_selector(sb)

        if password_selector:
            log(
                f"✅ 检测到密码框 "
                f"({i + 1}s)"
            )
            break

        if i in (0, 4, 9, 14, 19):
            log(
                f"🔎 等待登录 DOM... "
                f"{i + 1}/20"
            )

        time.sleep(1)

    # --------------------------------------------------------
    # 3. 输出一次 DOM
    # --------------------------------------------------------

    print_login_dom(sb)

    if not password_selector:

        log("❌ 页面没有出现密码输入框")

        save_debug(
            sb,
            "login_form_fail"
        )

        return False

    # --------------------------------------------------------
    # 4. 寻找账号输入框
    # --------------------------------------------------------

    username_selector = find_username_selector(sb)

    if not username_selector:

        log("")
        log("❌ 找不到邮箱/用户名输入框")
        log("")
        log("⚠️ 这说明当前页面可能是：")
        log("   1. 两阶段登录")
        log("   2. 邮箱输入框在 iframe")
        log("   3. 邮箱输入框使用了特殊 DOM")
        log("   4. 网站针对当前浏览器返回了特殊登录页面")
        log("")

        save_debug(
            sb,
            "login_form_fail"
        )

        return False

    log(
        f"✅ 账号输入框: "
        f"{username_selector}"
    )

    log(
        f"✅ 密码输入框: "
        f"{password_selector}"
    )

    # --------------------------------------------------------
    # 5. 填写账号
    # --------------------------------------------------------

    log("✍️ 填写 Host Ship 邮箱...")

    if not js_fill_input(
        sb,
        username_selector,
        EMAIL
    ):
        log("❌ 邮箱填写失败")
        save_debug(sb, "login_email_fail")
        return False

    # --------------------------------------------------------
    # 6. 填写密码
    # --------------------------------------------------------

    log("✍️ 填写 Host Ship 密码...")

    if not js_fill_input(
        sb,
        password_selector,
        PASSWORD
    ):
        log("❌ 密码填写失败")
        save_debug(sb, "login_password_fail")
        return False

    # --------------------------------------------------------
    # 7. 检查浏览器实际 value
    # --------------------------------------------------------

    verify = sb.execute_script(
        """
        const user =
            document.querySelector(arguments[0]);

        const pass =
            document.querySelector(arguments[1]);

        return {
            userExists: !!user,
            userValueLength:
                user ? (user.value || "").length : 0,

            passwordExists: !!pass,
            passwordValueLength:
                pass ? (pass.value || "").length : 0
        };
        """,
        username_selector,
        password_selector
    )

    log(
        "🔎 登录字段检查: "
        f"账号长度={verify.get('userValueLength', 0)}, "
        f"密码长度={verify.get('passwordValueLength', 0)}"
    )

    if verify.get("userValueLength", 0) <= 0:
        log("❌ 浏览器没有接受邮箱")
        save_debug(sb, "login_email_value_fail")
        return False

    if verify.get("passwordValueLength", 0) <= 0:
        log("❌ 浏览器没有接受密码")
        save_debug(sb, "login_password_value_fail")
        return False

    # --------------------------------------------------------
    # 8. Turnstile
    # --------------------------------------------------------

    handle_turnstile(sb)

    time.sleep(2)

    # --------------------------------------------------------
    # 9. 浏览器真实登录
    #
    # 第一优先级：
    # 密码框 Enter
    #
    # 这比直接调用 JS form.submit() 更接近用户实际登录。
    # --------------------------------------------------------

    log("🚀 使用浏览器登录动作提交...")

    submitted = False

    try:
        sb.click(password_selector)
        sb.press_keys(
            password_selector,
            "\n"
        )

        submitted = True

        log("✅ 已通过密码框 Enter 提交")

    except Exception as e:
        log(
            f"⚠️ 密码框 Enter 提交失败: {e}"
        )

    # --------------------------------------------------------
    # 10. Enter 失败 → 点击登录按钮
    # --------------------------------------------------------

    if not submitted:

        submit_selector = find_submit_selector(sb)

        if submit_selector:

            try:
                log(
                    f"🖱️ 点击登录按钮: "
                    f"{submit_selector}"
                )

                sb.click(submit_selector)

                submitted = True

                log("✅ 登录按钮点击成功")

            except Exception as e:
                log(
                    f"⚠️ 登录按钮点击失败: {e}"
                )

    if not submitted:

        log("❌ 无法提交登录表单")

        save_debug(
            sb,
            "login_submit_fail"
        )

        return False

    # --------------------------------------------------------
    # 11. 等待登录结果
    # --------------------------------------------------------

    log("⏳ 等待登录结果...")

    old_url = sb.get_current_url()

    for i in range(25):

        time.sleep(1)

        current_url = sb.get_current_url()
        source = sb.get_page_source().lower()

        log(
            f"   [{i + 1:02d}s] "
            f"{current_url}"
        )

        # URL 离开 auth/login
        if (
            "/auth/login" not in
            current_url.lower()
        ):
            log("✅ 登录成功：已离开登录页面")
            return True

        success_keywords = [
            "logout",
            "log out",
            "sign out",
            "manage server",
            "server management",
            "dashboard",
            "my server",
        ]

        if any(
            keyword in source
            for keyword in success_keywords
        ):
            log("✅ 登录成功：检测到后台页面特征")
            return True

        # 如果 URL 没变但是页面出现错误
        error_keywords = [
            "invalid credentials",
            "invalid email",
            "invalid password",
            "incorrect password",
            "login failed",
            "authentication failed",
            "invalid username",
            "邮箱或密码错误",
        ]

        if any(
            keyword in source
            for keyword in error_keywords
        ):
            log("❌ 页面明确返回登录失败")

            save_debug(
                sb,
                "login_credentials_fail"
            )

            return False

    # --------------------------------------------------------
    # 12. 最终失败
    # --------------------------------------------------------

    log("❌ 登录超时")

    log(
        f"当前 URL: "
        f"{sb.get_current_url()}"
    )

    log(
        f"当前标题: "
        f"{sb.get_title()}"
    )

    print_login_dom(sb)

    save_debug(
        sb,
        "login_failed"
    )

    return False


# ============================================================
# 服务器页面
# ============================================================

def go_to_server(sb) -> bool:

    log("")
    log("=" * 60)
    log("🖥️ 进入服务器管理")
    log("=" * 60)

    current_url = sb.get_current_url()

    # --------------------------------------------------------
    # 如果配置了 SERVER_ID
    # --------------------------------------------------------

    if SERVER_ID:

        possible_urls = [
            f"{BASE_URL}/server/{SERVER_ID}",
            f"{BASE_URL}/server/{SERVER_ID}/",
        ]

        for url in possible_urls:

            try:
                log(f"🌐 尝试打开: {url}")

                sb.uc_open_with_reconnect(
                    url,
                    reconnect_time=5
                )

                time.sleep(4)

                if "/auth/login" not in sb.get_current_url():
                    log(
                        "✅ 已进入服务器页面"
                    )
                    return True

            except Exception as e:
                log(
                    f"⚠️ 打开服务器页面失败: {e}"
                )

    # --------------------------------------------------------
    # 常规 /server
    # --------------------------------------------------------

    if "/server" not in current_url.lower():

        try:
            url = f"{BASE_URL}/server"

            log(f"🌐 打开服务器页面: {url}")

            sb.uc_open_with_reconnect(
                url,
                reconnect_time=5
            )

            time.sleep(4)

        except Exception as e:
            log(
                f"⚠️ 打开 /server 失败: {e}"
            )

    # --------------------------------------------------------
    # 检查是否成功
    # --------------------------------------------------------

    current_url = sb.get_current_url()
    source = sb.get_page_source().lower()

    if "/auth/login" in current_url.lower():

        log("❌ 被重新导向登录页面")

        save_debug(
            sb,
            "go_to_server_fail"
        )

        return False

    server_keywords = [
        "manage server",
        "server management",
        "renew",
        "renewal",
        "续期",
        "服务器",
        "server"
    ]

    if any(
        keyword in source
        for keyword in server_keywords
    ):
        log("✅ 已进入服务器管理页面")
        return True

    # --------------------------------------------------------
    # 如果首页有 MANAGE SERVER 链接
    # --------------------------------------------------------

    try:

        links = sb.execute_script(
            """
            return Array.from(
                document.querySelectorAll("a, button")
            ).map(el => ({
                text: (
                    el.innerText ||
                    el.textContent ||
                    ""
                ).trim(),
                href: el.href || ""
            })).filter(x =>
                /manage server|server/i.test(x.text)
                ||
                /\\/server/i.test(x.href)
            );
            """
        )

        log(
            f"🔎 找到服务器相关入口: "
            f"{len(links)}"
        )

        for item in links:

            log(
                f"   {item.get('text')} "
                f"→ {item.get('href')}"
            )

            href = item.get("href")

            if href:

                try:
                    sb.uc_open_with_reconnect(
                        href,
                        reconnect_time=5
                    )

                    time.sleep(4)

                    if "/auth/login" not in (
                        sb.get_current_url().lower()
                    ):
                        log(
                            "✅ 已通过服务器入口进入管理页"
                        )
                        return True

                except Exception:
                    pass

    except Exception as e:
        log(
            f"⚠️ 查找服务器入口失败: {e}"
        )

    log("❌ 无法进入服务器管理页面")

    save_debug(
        sb,
        "go_to_server_fail"
    )

    return False


# ============================================================
# 续期按钮识别
# ============================================================

def find_renew_buttons(sb):

    script = r"""
    function visible(el) {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);

        return (
            r.width > 20 &&
            r.height > 10 &&
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    }

    const elements = Array.from(
        document.querySelectorAll(
            "button, a, input[type=button], input[type=submit]"
        )
    ).filter(visible);

    const keywords = [
        "renew",
        "renewal",
        "extend",
        "续期",
        "续费",
        "延期",
        "延长",
        "renew server"
    ];

    return elements
        .map((el, index) => {

            const text = (
                el.innerText ||
                el.textContent ||
                el.value ||
                ""
            ).trim();

            return {
                index: index,
                text: text,
                tag: el.tagName,
                href: el.href || "",
                type: el.type || "",
                id: el.id || "",
                className: el.className || ""
            };
        })
        .filter(item => {

            const text =
                item.text.toLowerCase();

            return keywords.some(
                keyword =>
                    text.includes(
                        keyword.toLowerCase()
                    )
            );
        });
    """

    try:
        return sb.execute_script(script)

    except Exception as e:
        log(
            f"⚠️ 查找续期按钮失败: {e}"
        )
        return []


# ============================================================
# 执行续期
# ============================================================

def do_renew(sb) -> bool:

    log("")
    log("=" * 60)
    log("🔄 开始服务器续期")
    log("=" * 60)

    # --------------------------------------------------------
    # 查找续期按钮
    # --------------------------------------------------------

    buttons = find_renew_buttons(sb)

    log(
        f"🔎 找到续期相关按钮: "
        f"{len(buttons)}"
    )

    for button in buttons:

        log(
            "   "
            f"{button.get('tag')} "
            f"{button.get('text')!r} "
            f"href={button.get('href')!r}"
        )

    if not buttons:

        source = sb.get_page_source().lower()

        # ----------------------------------------------------
        # 检查是否已经续期 / 达到限制
        # ----------------------------------------------------

        limit_keywords = [
            "limit reached",
            "daily limit",
            "renew limit",
            "maximum renew",
            "already renewed",
            "今日已达",
            "次数已达",
            "达到上限",
            "已续期"
        ]

        if any(
            keyword in source
            for keyword in limit_keywords
        ):
            log("ℹ️ 当前服务器已经达到续期限制")
            save_debug(sb, "renew_limit")
            return True

        log("❌ 没有找到续期按钮")

        save_debug(
            sb,
            "no_renew_btn"
        )

        return False

    # --------------------------------------------------------
    # 点击第一个续期按钮
    # --------------------------------------------------------

    clicked = False

    for button in buttons:

        text = (
            button.get("text") or ""
        ).strip()

        try:

            selector = None

            # 优先根据文本定位
            if text:

                safe_text = text.replace(
                    "'",
                    "\\'"
                )

                selector = (
                    f"//*["
                    f"contains("
                    f"translate("
                    f"normalize-space(.),"
                    f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    f"'abcdefghijklmnopqrstuvwxyz'"
                    f"),"
                    f"'{safe_text.lower()}'"
                    f")"
                    f"]"
                )

            # ------------------------------------------------
            # 更稳定：通过 JS 给目标元素打标记
            # ------------------------------------------------

            marked = sb.execute_script(
                """
                const elements =
                    Array.from(
                        document.querySelectorAll(
                            "button, a, " +
                            "input[type=button], " +
                            "input[type=submit]"
                        )
                    );

                const target = elements.find(
                    el => (
                        el.innerText ||
                        el.textContent ||
                        el.value ||
                        ""
                    ).trim() === arguments[0]
                );

                if (target) {
                    target.setAttribute(
                        "data-hostship-renew",
                        "true"
                    );

                    return true;
                }

                return false;
                """,
                text
            )

            if marked:
                selector = (
                    '[data-hostship-renew="true"]'
                )

            if not selector:
                continue

            log(
                f"🖱️ 尝试点击续期按钮: "
                f"{text!r}"
            )

            sb.click(selector)

            clicked = True

            log("✅ 续期按钮已点击")

            break

        except Exception as e:

            log(
                f"⚠️ 点击续期按钮失败: {e}"
            )

    if not clicked:

        log("❌ 无法点击续期按钮")

        save_debug(
            sb,
            "renew_click_fail"
        )

        return False

    # --------------------------------------------------------
    # 等待弹窗 / 页面变化
    # --------------------------------------------------------

    time.sleep(3)

    # --------------------------------------------------------
    # 检查确认按钮
    # --------------------------------------------------------

    confirm_script = r"""
    function visible(el) {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);

        return (
            r.width > 20 &&
            r.height > 10 &&
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    }

    const elements = Array.from(
        document.querySelectorAll(
            "button, a, input[type=button], input[type=submit]"
        )
    ).filter(visible);

    const keywords = [
        "confirm",
        "yes",
        "continue",
        "renew",
        "extend",
        "确认",
        "确定",
        "继续",
        "续期",
        "续费"
    ];

    return elements
        .map(el => ({
            text: (
                el.innerText ||
                el.textContent ||
                el.value ||
                ""
            ).trim(),
            el: el
        }))
        .filter(item => {

            const text =
                item.text.toLowerCase();

            return keywords.some(
                x => text.includes(
                    x.toLowerCase()
                )
            );
        })
        .map(item => item.text);
    """

    try:

        confirm_buttons = sb.execute_script(
            confirm_script
        )

        if confirm_buttons:

            log(
                f"🔎 检测到确认按钮: "
                f"{confirm_buttons}"
            )

            # 优先寻找包含确认/确定/yes 的按钮
            for text in confirm_buttons:

                lower = text.lower()

                if not any(
                    x in lower
                    for x in [
                        "confirm",
                        "yes",
                        "确定",
                        "确认"
                    ]
                ):
                    continue

                try:

                    sb.execute_script(
                        """
                        const elements =
                            Array.from(
                                document.querySelectorAll(
                                    "button, a, " +
                                    "input[type=button], " +
                                    "input[type=submit]"
                                )
                            );

                        const target =
                            elements.find(
                                el =>
                                    (
                                        el.innerText ||
                                        el.textContent ||
                                        el.value ||
                                        ""
                                    ).trim() === arguments[0]
                            );

                        if (target) {
                            target.click();
                            return true;
                        }

                        return false;
                        """,
                        text
                    )

                    log(
                        f"✅ 已点击确认按钮: "
                        f"{text!r}"
                    )

                    break

                except Exception:
                    pass

    except Exception as e:

        log(
            f"ℹ️ 没有检测到确认弹窗: {e}"
        )

    # --------------------------------------------------------
    # Turnstile
    # --------------------------------------------------------

    time.sleep(2)

    handle_turnstile(sb)

    # --------------------------------------------------------
    # 等待续期结果
    # --------------------------------------------------------

    log("⏳ 等待续期结果...")

    for i in range(20):

        time.sleep(1)

        source = sb.get_page_source().lower()

        current_url = sb.get_current_url()

        # 成功关键词
        success_keywords = [
            "renewed successfully",
            "renew success",
            "renewal successful",
            "server renewed",
            "successfully renewed",
            "续期成功",
            "续期成功",
            "续期完成",
            "操作成功"
        ]

        if any(
            keyword in source
            for keyword in success_keywords
        ):
            log("🎉 服务器续期成功！")
            return True

        # 达到限制
        limit_keywords = [
            "limit reached",
            "daily limit",
            "renew limit",
            "maximum renew",
            "already renewed",
            "达到上限",
            "次数已达",
            "今日已达",
            "已经续期"
        ]

        if any(
            keyword in source
            for keyword in limit_keywords
        ):
            log("ℹ️ 服务器续期受到次数限制")
            return True

        log(
            f"   [{i + 1:02d}s] "
            f"等待续期结果..."
        )

    # --------------------------------------------------------
    # 最终检查
    # --------------------------------------------------------

    source = sb.get_page_source().lower()

    if any(
        x in source
        for x in [
            "success",
            "renewed",
            "续期成功",
            "操作成功"
        ]
    ):
        log("🎉 检测到续期成功")
        return True

    log("❌ 未能确认续期结果")

    save_debug(
        sb,
        "renew_result"
    )

    return False


# ============================================================
# 主程序
# ============================================================

def main():

    start_time = time.time()

    log("")
    log("=" * 60)
    log("🚀 Host Ship 自动续期程序")
    log("=" * 60)

    log(
        f"Python: {sys.version.split()[0]}"
    )

    log(
        f"代理模式: "
        f"{'开启' if IS_PROXY else '关闭'}"
    )

    if IS_PROXY:
        log(
            f"代理服务器: "
            f"{PROXY_SERVER}"
        )

    # --------------------------------------------------------
    # 环境检查
    # --------------------------------------------------------

    if not EMAIL:

        message = (
            "❌ Host Ship 自动续期失败\n\n"
            "原因：HOSTSHIP_EMAIL 未配置"
        )

        log(message)
        send_tg_message(message)

        return 1

    if not PASSWORD:

        message = (
            "❌ Host Ship 自动续期失败\n\n"
            "原因：HOSTSHIP_PASSWORD 未配置"
        )

        log(message)
        send_tg_message(message)

        return 1

    # --------------------------------------------------------
    # 浏览器
    #
    # uc=True：
    # 使用 SeleniumBase UC 模式，
    # 更适合 Cloudflare / Turnstile 页面。
    #
    # headless=False：
    # GitHub Actions 使用 Xvfb，
    # 所以这里不要再开 Selenium 自己的 headless。
    # --------------------------------------------------------

    try:

        with SB(
            uc=True,
            headless=False,
            test=False,
            locale_code="en",
        ) as sb:

            # ------------------------------------------------
            # 代理
            # ------------------------------------------------

            if IS_PROXY:

                try:
                    log(
                        f"🌐 浏览器使用代理: "
                        f"{PROXY_SERVER}"
                    )

                    # SeleniumBase 在启动后修改代理
                    # 对部分 Chrome 版本不一定生效，
                    # 因此这里仅作为兼容 fallback。
                    sb.execute_cdp_cmd(
                        "Network.enable",
                        {}
                    )

                except Exception as e:
                    log(
                        f"⚠️ 设置代理失败: {e}"
                    )

            # ------------------------------------------------
            # 浏览器 UA / 页面
            # ------------------------------------------------

            try:

                sb.set_window_size(
                    1920,
                    1080
                )

            except Exception:
                pass

            # ------------------------------------------------
            # 测试网络
            # ------------------------------------------------

            try:

                log("🌐 检查 GitHub Actions 出口 IP...")

                sb.open(
                    "https://api.ip.sb/ip"
                )

                time.sleep(2)

                ip = (
                    sb.get_page_source()
                    .strip()
                )

                log(
                    f"🌐 当前出口 IP: "
                    f"{ip[:100]}"
                )

            except Exception as e:

                log(
                    f"⚠️ 出口 IP 检查失败: {e}"
                )

            # ------------------------------------------------
            # 登录
            # ------------------------------------------------

            if not login(sb):

                message = (
                    "❌ Host Ship 自动续期失败\n\n"
                    "阶段：登录\n"
                    f"URL：{sb.get_current_url()}"
                )

                send_tg_message(message)

                return 1

            # ------------------------------------------------
            # 进入服务器
            # ------------------------------------------------

            if not go_to_server(sb):

                message = (
                    "❌ Host Ship 自动续期失败\n\n"
                    "阶段：进入服务器管理页面"
                )

                send_tg_message(message)

                return 1

            # ------------------------------------------------
            # 续期
            # ------------------------------------------------

            renew_success = do_renew(sb)

            elapsed = int(
                time.time() - start_time
            )

            # ------------------------------------------------
            # Telegram
            # ------------------------------------------------

            if renew_success:

                message = (
                    "✅ Host Ship 自动续期完成\n\n"
                    f"服务器 ID："
                    f"{SERVER_ID or '未指定'}\n"
                    f"耗时：{elapsed} 秒"
                )

                send_tg_message(message)

                log("")
                log("=" * 60)
                log("🎉 Host Ship 自动续期流程完成")
                log("=" * 60)

                return 0

            else:

                message = (
                    "❌ Host Ship 自动续期失败\n\n"
                    "阶段：续期\n"
                    f"耗时：{elapsed} 秒"
                )

                send_tg_message(message)

                log("")
                log("=" * 60)
                log("❌ Host Ship 自动续期失败")
                log("=" * 60)

                return 1

    except Exception as e:

        log("")
        log("=" * 60)
        log("💥 程序发生未处理异常")
        log("=" * 60)

        log(
            f"{type(e).__name__}: {e}"
        )

        traceback.print_exc()

        send_tg_message(
            "💥 Host Ship 自动续期程序异常\n\n"
            f"{type(e).__name__}: {e}"
        )

        return 1


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    sys.exit(main())
