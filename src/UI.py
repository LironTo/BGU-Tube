import asyncio
import os
import re
import sys
import threading
from collections import defaultdict
from tkinter import *
from tkinter import messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from playwright.async_api import async_playwright
import httpx
from tkinter.ttk import Progressbar
from functools import partial

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    DOWNLOADS_DIR = os.path.join(os.path.dirname(sys.executable), 'downloads')
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DOWNLOADS_DIR = os.path.join(BASE_DIR, 'downloads')
sys.path.append(BASE_DIR)

USERNAME = ""
PASSWORD = ""
MOODLE_LOGIN_URL = "https://moodle.bgu.ac.il/moodle/login/index.php"
PROFILE_URL = "https://moodle.bgu.ac.il/moodle/user/profile.php"
MAX_CONCURRENT_DOWNLOADS = 3

# ---- Theme (colors taken from Media/Logo.png) ----
LIGHT_BLUE = "#b6e9fd"   # window background - matches the logo background
ORANGE = "#fe6f1c"       # primary actions / accents
ORANGE_DARK = "#d95a10"  # hover / pressed
WHITE = "#fefefe"        # cards / lists
DARK_BLUE = "#001e26"    # text
MUTED_BLUE = "#537b89"   # secondary text
DISABLED_BG = "#cfe0e8"
DISABLED_FG = "#8fa9b3"
FONT = "Segoe UI"


def setup_theme(root):
    root.configure(bg=LIGHT_BLUE)
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("Primary.TButton", font=(FONT, 12, "bold"), padding=(24, 8),
                    background=ORANGE, foreground=WHITE, bordercolor=ORANGE,
                    borderwidth=0, focuscolor=WHITE)
    style.map("Primary.TButton",
              background=[("disabled", DISABLED_BG), ("pressed", ORANGE_DARK), ("active", ORANGE_DARK)],
              foreground=[("disabled", DISABLED_FG)])

    style.configure("Secondary.TButton", font=(FONT, 11), padding=(18, 6),
                    background=WHITE, foreground=DARK_BLUE, bordercolor=MUTED_BLUE,
                    borderwidth=1, focuscolor=DARK_BLUE)
    style.map("Secondary.TButton",
              background=[("disabled", DISABLED_BG), ("active", "#e8f6fd")],
              foreground=[("disabled", DISABLED_FG)])

    # במבנה clam תיבת הסימון נצבעת דרך indicatorbackground/indicatorforeground
    checkbox_colors = dict(indicatorbackground=WHITE, indicatorforeground=WHITE,
                           upperbordercolor=MUTED_BLUE, lowerbordercolor=MUTED_BLUE,
                           indicatormargin=(6, 2, 2, 2))
    style.configure("Sky.TCheckbutton", font=(FONT, 12), background=LIGHT_BLUE,
                    foreground=DARK_BLUE, focuscolor=LIGHT_BLUE, **checkbox_colors)
    style.map("Sky.TCheckbutton",
              background=[("active", LIGHT_BLUE)],
              indicatorbackground=[("selected", ORANGE)])

    style.configure("Card.TCheckbutton", font=(FONT, 12), background=WHITE,
                    foreground=DARK_BLUE, focuscolor=WHITE, **checkbox_colors)
    style.map("Card.TCheckbutton",
              background=[("active", "#e8f6fd")],
              indicatorbackground=[("selected", ORANGE)])

    style.configure("CardSmall.TCheckbutton", font=(FONT, 10), background=WHITE,
                    foreground=MUTED_BLUE, focuscolor=WHITE, **checkbox_colors)
    style.map("CardSmall.TCheckbutton",
              background=[("active", "#e8f6fd")],
              indicatorbackground=[("selected", ORANGE)])

    # פריסת RTL: תיבת הסימון מימין לטקסט
    rtl_check_layout = [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Checkbutton.indicator", {"side": "right", "sticky": ""}),
        ("Checkbutton.focus", {"side": "right", "sticky": "", "children": [
            ("Checkbutton.label", {"sticky": "nswe"})]})]})]
    for name in ("Sky.TCheckbutton", "Card.TCheckbutton", "CardSmall.TCheckbutton"):
        style.layout(name, rtl_check_layout)

    style.configure("BGU.Horizontal.TProgressbar", troughcolor=WHITE,
                    background=ORANGE, bordercolor=LIGHT_BLUE,
                    lightcolor=ORANGE, darkcolor=ORANGE, thickness=14)

    style.configure("Vertical.TScrollbar", background=LIGHT_BLUE, troughcolor=WHITE,
                    bordercolor=WHITE, arrowcolor=DARK_BLUE)
    style.map("Vertical.TScrollbar", background=[("active", "#9dd9f2")])


def course_header(parent, text):
    # כותרת קורס בתוך רשימה: משולש "נגן" כתום בסגנון הלוגו מימין לשם הקורס (RTL)
    row = Frame(parent, bg=WHITE)
    Label(row, text="▶", font=(FONT, 11), bg=WHITE, fg=ORANGE).pack(side=RIGHT, padx=(6, 10))
    Label(row, text=text, font=(FONT, 13, "bold"), bg=WHITE, fg=DARK_BLUE).pack(side=RIGHT)
    row.pack(fill="x", pady=(12, 2))


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def get_unique_filename(folder, base_name, used_paths, extension=".mp4"):
    i = 0
    candidate = os.path.join(folder, f"{base_name}{extension}")
    while os.path.exists(candidate) or candidate in used_paths:
        i += 1
        candidate = os.path.join(folder, f"{base_name} ({i}){extension}")
    used_paths.add(candidate)
    return candidate


class BGUTubeApp:
    def __init__(self, root):
        print("[INIT] Initializing GUI")
        self.root = root
        self.root.title("BGU Tube")
        self.root.resizable(False, False)
        setup_theme(self.root)

        # חלון בגודל אחיד, ממורכז על המסך, בהתאמה לקנה המידה של התצוגה (DPI)
        self.scale = self.root.winfo_fpixels("1i") / 96
        win_w, win_h = int(480 * self.scale), int(720 * self.scale)
        win_x = (self.root.winfo_screenwidth() - win_w) // 2
        win_y = max((self.root.winfo_screenheight() - win_h) // 2 - 20, 0)
        self.root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")

        self.course_vars = []

        self.browser = None
        self.context = None
        self.page = None
        self.selected_courses = []
        self.uploader_vars = []

        # לולאת asyncio רצה ב-Thread נפרד כדי שה-GUI לא ייתקע בזמן פעולות רשת.
        # כל עדכון Widgets חוזר ל-Main Thread דרך self.root.after (Tkinter אינו Thread-safe).
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        try:
            logo_path = os.path.join(BASE_DIR, "Media", "Logo.png")
            logo_size = int(150 * self.scale)
            self.logo_img = ImageTk.PhotoImage(Image.open(logo_path).resize((logo_size, logo_size)))
            self.logo = Label(root, image=self.logo_img, bg=LIGHT_BLUE, bd=0)
            self.root.iconphoto(True, self.logo_img)
        except:
            self.logo = Label(root, text="BGU Tube", font=(FONT, 24, "bold"), bg=LIGHT_BLUE, fg=DARK_BLUE)
        self.logo.pack(pady=(10, 4))

        # מחוון שלבים: ארבע נקודות, שלב 1 בצד ימין (RTL)
        self.steps_frame = Frame(root, bg=LIGHT_BLUE)
        self.step_dots = []
        for _ in range(4):
            dot = Label(self.steps_frame, text="●", font=(FONT, 10), bg=LIGHT_BLUE, fg=WHITE)
            dot.pack(side=RIGHT, padx=3)
            self.step_dots.append(dot)

        entry_style = dict(font=(FONT, 13), bg=WHITE, fg=DARK_BLUE, relief=FLAT, bd=0,
                           insertbackground=DARK_BLUE, highlightthickness=2,
                           highlightbackground=WHITE, highlightcolor=ORANGE)
        self.user_label = Label(root, text="שם משתמש", font=(FONT, 12), bg=LIGHT_BLUE, fg=DARK_BLUE, anchor="e")
        self.user_entry = Entry(root, **entry_style)
        self.pass_label = Label(root, text="סיסמה", font=(FONT, 12), bg=LIGHT_BLUE, fg=DARK_BLUE, anchor="e")
        self.pass_entry = Entry(root, show="•", **entry_style)
        self.user_entry.bind("<Return>", lambda e: self.on_login())
        self.pass_entry.bind("<Return>", lambda e: self.on_login())
        self.login_error = Label(root, text="", font=(FONT, 11), bg=LIGHT_BLUE, fg="#c0392b",
                                 wraplength=int(380 * self.scale), justify="center")

        try:
            from Media.LoginInfo import USERNAME, PASSWORD
            self.user_entry.insert(0, USERNAME)
            self.pass_entry.insert(0, PASSWORD)
        except:
            pass

        self.login_btn = ttk.Button(root, text="התחבר", style="Primary.TButton", cursor="hand2",
                                    command=self.on_login)

        self.course_frame = Frame(root, bg=LIGHT_BLUE)
        # גובה קבוע לרשימה כדי שהכפתורים בתחתית תמיד ייכנסו לחלון
        self.canvas = Canvas(self.course_frame, bg=WHITE, highlightthickness=0,
                             height=int(220 * self.scale))
        self.scrollable_frame = Frame(self.canvas, bg=WHITE)
        self.scrollbar = ttk.Scrollbar(self.course_frame, orient=VERTICAL, command=self.canvas.yview)

        # מתיחת המסגרת הפנימית לרוחב ה-Canvas כדי שיישור לימין יעבוד
        window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(window_id, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=RIGHT, fill=BOTH, expand=True)
        self.scrollbar.pack(side=LEFT, fill=Y)

        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.log_out = ttk.Button(self.root, text="התנתק", style="Secondary.TButton", cursor="hand2",
                                  command=self.logout)
        self.your_courses = Label(self.root, text="הקורסים שלך:", font=(FONT, 17, "bold"),
                                  bg=LIGHT_BLUE, fg=DARK_BLUE, anchor="e")
        self.course_count = Label(self.root, text="", font=(FONT, 11), bg=LIGHT_BLUE, fg=MUTED_BLUE)

        self.select_all_var = IntVar()
        self.select_all_chk = ttk.Checkbutton(self.root, text="בחר/י את כל הקורסים", variable=self.select_all_var,
                                              style="Sky.TCheckbutton", cursor="hand2",
                                              command=self.toggle_select_all)

        self.show_selected_btn = ttk.Button(self.root, text="הצג קורסים שנבחרו", style="Secondary.TButton",
                                            cursor="hand2", command=self.show_selected_courses, state=DISABLED)

        self.go_to_uploaders_btn = ttk.Button(self.root, text="עבור לבחירת מרצים", style="Primary.TButton",
                                              cursor="hand2", command=self.go_to_uploaders_screen, state=DISABLED)

        self.selected_uploaders = {}
        self.all_courses = []
        self.download_btn = ttk.Button(self.root, text="הורד/י הקלטות", style="Primary.TButton",
                                       cursor="hand2", command=self.go_to_download_screen, state=DISABLED)

        self.progress = None
        self.progress_status = None
        self.progress_file = None
        self.total_recordings = 0
        self.back_btn = None
        self.download_button = None  # נשתמש בשם ברור יותר לכפתור ההורדה

        self.loading_label = None
        self.loading_bar = None

        self.login_page()

    def show_steps(self, current):
        # שלבים שהושלמו - כחול כהה, השלב הנוכחי - כתום, שלבים עתידיים - לבן
        for i, dot in enumerate(self.step_dots, start=1):
            dot.config(fg=ORANGE if i == current else DARK_BLUE if i < current else WHITE)
        self.steps_frame.pack(pady=(0, 4))

    def login_page(self):
        self.show_steps(1)
        self.user_label.pack(fill="x", padx=70)
        self.user_entry.pack(pady=5, padx=70, fill="x")
        self.pass_label.pack(fill="x", padx=70)
        self.pass_entry.pack(pady=5, padx=70, fill="x")
        self.login_btn.pack(pady=20)
        self.user_entry.focus_set()

    def show_loading(self, text):
        self.hide_loading()
        self.loading_label = Label(self.root, text=text, font=(FONT, 12), bg=LIGHT_BLUE, fg=DARK_BLUE)
        self.loading_label.pack(pady=(10, 0))
        self.loading_bar = ttk.Progressbar(self.root, mode="indeterminate", length=int(250 * self.scale),
                                           style="BGU.Horizontal.TProgressbar")
        self.loading_bar.pack(pady=5)
        self.loading_bar.start(10)

    def hide_loading(self):
        if self.loading_bar is not None:
            self.loading_bar.stop()
            self.loading_bar.destroy()
            self.loading_bar = None
        if self.loading_label is not None:
            self.loading_label.destroy()
            self.loading_label = None

    def clean_up(self):
        self.hide_loading()
        for widget in self.root.winfo_children():
            if widget != self.logo:
                widget.pack_forget()
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.course_vars.clear()
        self.uploader_vars.clear()

    def on_login(self):
        global USERNAME, PASSWORD
        if self.login_btn.instate(["disabled"]):
            return
        self.login_error.pack_forget()
        USERNAME = self.user_entry.get()
        PASSWORD = self.pass_entry.get()
        print("[INFO] Login button clicked.")
        self.login_btn.config(state=DISABLED)
        self.show_loading("מתחבר וטוען קורסים...")
        asyncio.run_coroutine_threadsafe(self.login_and_fetch_courses(), self.loop)

    async def save_error_screenshot(self, name, page=None):
        page = page or self.page
        if page is None:
            return
        try:
            path = os.path.join(os.path.dirname(DOWNLOADS_DIR), f"error_{name}.png")
            await page.screenshot(path=path)
            print(f"[WARN] Screenshot saved to: {path}")
        except Exception as e:
            print(f"[WARN] Failed to take screenshot: {e}")

    async def login_and_fetch_courses(self):
        print("[INFO] Starting Playwright...")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

        try:
            await self.page.goto(MOODLE_LOGIN_URL)
            try:
                await self.page.fill('#username', USERNAME)
                await self.page.fill('#password', PASSWORD)
                await self.page.click('#loginbtn')
            except Exception as e:
                print(f"[WARN] Login form selectors failed - Moodle frontend may have changed: {e}")
                await self.save_error_screenshot("login_form")
                raise
            await self.page.wait_for_timeout(3000)

            await self.page.goto(PROFILE_URL)
            await self.page.wait_for_timeout(2000)
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            links = await self.page.locator("a[href*='user/view.php'][href*='course=']").all()
            seen = set()
            course_urls = []

            for a in links:
                title = (await a.inner_text()).strip()
                href = await a.get_attribute("href")
                if not href or not title or "course=" not in href:
                    continue
                course_id = href.split("course=")[-1].split("&")[0]
                course_url = f"https://moodle.bgu.ac.il/moodle/course/view.php?id={course_id}"
                if course_url in seen:
                    continue
                seen.add(course_url)
                course_urls.append((title, course_url))

            print(f"[INFO] Total courses found: {len(course_urls)}")

            if not course_urls:
                print("[WARN] No course links found on profile page - selectors may be outdated.")
                await self.save_error_screenshot("profile_no_courses")

            self.root.after(0, lambda: self.show_courses_screen(course_urls))

        except Exception as e:
            print(f"[ERROR] {e}")
            await self.save_error_screenshot("login")
            self.root.after(0, self.hide_loading)
            self.root.after(0, self.show_login_error)
        self.root.after(0, lambda: self.login_btn.config(state=NORMAL))

    def show_login_error(self):
        self.login_error.config(text="ההתחברות נכשלה — בדקו את שם המשתמש והסיסמה ונסו שוב")
        self.login_error.pack(pady=(0, 10))

    def show_courses_screen(self, course_urls):
        self.all_courses = course_urls
        self.clean_up()
        self.show_steps(2)
        self.your_courses.pack(fill="x", padx=30)
        self.select_all_chk.pack(anchor="e", padx=26)
        self.course_frame.pack(pady=10, padx=20, fill=X)

        # שחזור בחירות קודמות (למשל בחזרה ממסך המרצים)
        previously_selected = {url for _, (_, url) in self.selected_courses}
        for title, url in course_urls:
            var = IntVar(value=1 if url in previously_selected else 0)
            chk = ttk.Checkbutton(self.scrollable_frame, text=title.strip(), variable=var,
                                  style="Card.TCheckbutton", cursor="hand2",
                                  command=self.update_download_button_state)
            chk.pack(anchor="e", padx=10, pady=2)
            self.course_vars.append((var, (title, url)))

        self.select_all_var.set(1 if previously_selected and len(previously_selected) == len(course_urls) else 0)
        self.update_download_button_state()

        self.course_count.config(text=f"סהכ קורסים שנמצאו: {len(course_urls)}")
        self.course_count.pack(pady=5)
        self.log_out.pack(pady=10)
        self.show_selected_btn.pack(pady=5)
        self.go_to_uploaders_btn.pack(pady=5)

    def logout(self):
        self.selected_courses = []
        self.selected_uploaders = {}
        self.select_all_var.set(0)
        self.clean_up()
        self.login_page()

    def update_download_button_state(self):
        any_selected = any(var.get() for var, _ in self.course_vars)
        self.show_selected_btn.config(state=NORMAL if any_selected else DISABLED)
        self.go_to_uploaders_btn.config(state=NORMAL if any_selected else DISABLED)

    def show_selected_courses(self):
        selected = [title for var, (title, _) in self.course_vars if var.get()]
        if not selected:
            messagebox.showinfo("לא נבחרו קורסים", "לא נבחרו קורסים להורדה.")
            return
        selected_text = "\n".join(selected)
        messagebox.showinfo("קורסים שנבחרו", f"הקורסים שנבחרו:\n\n{selected_text}")

    def toggle_select_all(self):
        new_state = self.select_all_var.get()
        for var, _ in self.course_vars:
            var.set(new_state)
        self.update_download_button_state()

    def go_to_uploaders_screen(self):
        self.selected_courses = [(var, (title, url)) for var, (title, url) in self.course_vars if var.get()]
        if not self.selected_courses:
            print("[WARN] No courses selected for uploaders screen.")
            messagebox.showinfo("שגיאה", "לא נבחרו קורסים.")
            return

        print(f"[INFO] Moving to uploader selection screen with {len(self.selected_courses)} selected courses.")
        self.clean_up()
        self.show_steps(3)
        Label(self.root, text="בחר/י מרצים או מתרגלים", font=(FONT, 16, "bold"),
              bg=LIGHT_BLUE, fg=DARK_BLUE).pack(pady=10)

        uploader_frame = Frame(self.root, bg=LIGHT_BLUE)
        canvas = Canvas(uploader_frame, bg=WHITE, highlightthickness=0,
                        height=int(230 * self.scale))
        scrollbar = ttk.Scrollbar(uploader_frame, orient=VERTICAL, command=canvas.yview)
        inner_frame = Frame(canvas, bg=WHITE)

        window_id = canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.pack(side=RIGHT, fill=BOTH, expand=True)
        scrollbar.pack(side=LEFT, fill=Y)
        uploader_frame.pack(fill=X, padx=10, pady=10)

        self.download_btn = ttk.Button(self.root, text="הורד/י הקלטות", style="Primary.TButton",
                                       cursor="hand2", state=DISABLED, command=self.go_to_download_screen)
        self.download_btn.pack(pady=(5, 2))
        ttk.Button(self.root, text="חזרה", style="Secondary.TButton", cursor="hand2",
                   command=lambda: self.show_courses_screen(self.all_courses)).pack(pady=(0, 10))

        self.show_loading("טוען רשימת מרצים ומתרגלים...")

        def render_course_uploaders(title, course_id, uploaders):
            course_header(inner_frame, title.strip())
            if not uploaders:
                Label(inner_frame, text="לא נמצאו הקלטות בקורס", font=(FONT, 11), bg=WHITE, fg=ORANGE_DARK).pack(
                    anchor="e", padx=27)
                return

            # שמירת הבחירה של המרצים
            self.selected_uploaders[course_id] = []
            course_uploader_vars = []
            all_var = IntVar()

            def refresh_download_state():
                self.download_btn.config(state=NORMAL if any(self.selected_uploaders.values()) else DISABLED)

            def toggle_course_all():
                checked = all_var.get()
                for v, _ in course_uploader_vars:
                    v.set(checked)
                self.selected_uploaders[course_id] = [n for _, n in course_uploader_vars] if checked else []
                refresh_download_state()

            ttk.Checkbutton(inner_frame, text="בחר/י את כל המרצים", variable=all_var,
                            style="CardSmall.TCheckbutton", cursor="hand2",
                            command=toggle_course_all).pack(anchor="e", padx=27)

            for name, count in uploaders.items():
                var = IntVar()
                cb = ttk.Checkbutton(inner_frame, text=f"{name} ({count} הקלטות)",
                                     style="Card.TCheckbutton", cursor="hand2", variable=var)
                cb.pack(anchor="e", padx=27)
                self.uploader_vars.append((var, name, course_id))
                course_uploader_vars.append((var, name))

                def update_state(v, uploader, cid):
                    if v.get():
                        if uploader not in self.selected_uploaders[cid]:
                            self.selected_uploaders[cid].append(uploader)
                    else:
                        if uploader in self.selected_uploaders[cid]:
                            self.selected_uploaders[cid].remove(uploader)
                    all_var.set(1 if len(self.selected_uploaders[cid]) == len(course_uploader_vars) else 0)
                    refresh_download_state()

                cb.config(command=lambda v=var, uploader=name, cid=course_id: update_state(v, uploader, cid))

        async def fetch_uploaders_for_selected():
            self.selected_uploaders.clear()
            page = self.page
            for var, (title, url) in self.selected_courses:
                course_id = url.split("id=")[-1]
                print(f"[INFO] Fetching uploaders for course: {title} (ID: {course_id})")
                uploaders = await self.get_course_media_uploaders(page, course_id)
                self.root.after(0, partial(render_course_uploaders, title, course_id, uploaders))
            self.root.after(0, self.hide_loading)

        asyncio.run_coroutine_threadsafe(fetch_uploaders_for_selected(), self.loop)

    async def get_course_media_uploaders(self, page, course_id):
        base_url = f"https://moodle.bgu.ac.il/moodle/blocks/video/videoslist.php?courseid={course_id}"
        uploads_by_person = defaultdict(int)

        print(f"[INFO] Fetching video data for course {course_id} from all pages...")

        await page.goto(base_url)
        await page.wait_for_timeout(1000)

        html = await page.content()
        page_numbers = re.findall(r'data-page-number="(\d+)"', html)
        total_pages = max([int(p) for p in page_numbers] or [1])
        print(f"[INFO] Total pages detected: {total_pages}")

        for page_index in range(total_pages):
            url = f"{base_url}&page={page_index}" if page_index > 0 else base_url
            print(f"[INFO] Navigating to: {url}")
            await page.goto(url)
            await page.wait_for_timeout(1000)

            try:
                await page.wait_for_selector("#videoslist_table", timeout=3000)
            except Exception as e:
                print(f"[WARN] Table not found on page {page_index + 1} - Moodle frontend may have changed: {e}")
                await self.save_error_screenshot("videoslist_table", page)
                continue

            rows = await page.locator("#videoslist_table tbody tr").all()
            valid_rows = [row for row in rows if "emptyrow" not in (await row.get_attribute("class") or "")]

            print(f"[INFO] Found {len(valid_rows)} rows in page {page_index + 1}.")

            for row in valid_rows:
                try:
                    owner_cell = await row.locator("td.c4").inner_text()
                    owner = owner_cell.strip()
                    if not owner:
                        continue
                    uploads_by_person[owner] += 1
                except Exception as e:
                    print(f"[WARN] Failed to read uploader cell (td.c4): {e}")
                    continue

        print(f"[INFO] Uploaders in course {course_id}:")
        for name, count in uploads_by_person.items():
            print(f"[INFO] Uploader: {name}, Recordings: {count}")

        return dict(uploads_by_person)

    def update_download_btn_state(self):
        any_selected = any(var.get() for var, _ in self.uploader_vars)
        self.download_btn.config(state=NORMAL if any_selected else DISABLED)

    def go_to_download_screen(self):
        print("[INFO] Moving to download screen...")
        self.clean_up()
        self.show_steps(4)

        Label(self.root, text="אישור לפני הורדה", font=(FONT, 16, "bold"),
              bg=LIGHT_BLUE, fg=DARK_BLUE).pack(pady=10)

        download_frame = Frame(self.root, bg=LIGHT_BLUE)
        canvas = Canvas(download_frame, bg=WHITE, highlightthickness=0,
                        height=int(200 * self.scale))
        scrollbar = ttk.Scrollbar(download_frame, orient=VERTICAL, command=canvas.yview)
        inner_frame = Frame(canvas, bg=WHITE)

        window_id = canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.pack(side=RIGHT, fill=BOTH, expand=True)
        scrollbar.pack(side=LEFT, fill=Y)
        download_frame.pack(fill=X, padx=10, pady=10)

        print("[INFO] Selecting uploaders for download: ", len(self.selected_uploaders))
        print("[INFO] Selected uploaders: ", self.selected_uploaders)#################################################################################

        # הצגת הקורסים והמרצים שנבחרו
        for course_id, uploaders in self.selected_uploaders.items():
            course_title = ""
            for _, (title, url) in self.selected_courses:
                if url.endswith(f"id={course_id}"):
                    course_title = title
                    break
            course_header(inner_frame, course_title)

            for uploader in uploaders:
                Label(inner_frame, text=uploader, font=(FONT, 12), bg=WHITE, fg=DARK_BLUE).pack(
                    anchor="e", padx=27)

        self.download_button = ttk.Button(self.root, text="התחל הורדה", style="Primary.TButton",
                                          cursor="hand2", command=self.start_downloads)
        self.download_button.pack(pady=(10, 2))
        self.back_btn = ttk.Button(self.root, text="חזרה", style="Secondary.TButton", cursor="hand2",
                                   command=self.go_to_uploaders_screen)
        self.back_btn.pack(pady=(0, 10))

    def start_downloads(self):
        print("[INFO] Starting downloads...")
        self.download_button.config(state=DISABLED)
        if self.back_btn is not None:
            self.back_btn.config(state=DISABLED)
        self.progress = Progressbar(self.root, orient=HORIZONTAL, length=int(400 * self.scale),
                                    mode='determinate', style="BGU.Horizontal.TProgressbar")
        self.progress.pack(pady=(10, 4))
        self.progress_status = Label(self.root, text="", font=(FONT, 12, "bold"), bg=LIGHT_BLUE, fg=DARK_BLUE)
        self.progress_status.pack()
        self.progress_file = Label(self.root, text="", font=(FONT, 10), bg=LIGHT_BLUE, fg=MUTED_BLUE,
                                   wraplength=int(420 * self.scale))
        self.progress_file.pack(pady=(0, 8))
        self.show_loading("סורק הקלטות בקורסים שנבחרו...")
        asyncio.run_coroutine_threadsafe(self.perform_downloads(), self.loop)

    async def perform_downloads(self):
        recordings = []
        self.selected_uploaders = {k: v for k, v in self.selected_uploaders.items() if v}
        for course_id, uploaders in self.selected_uploaders.items():
            course_title = ""
            for _, (title, url) in self.selected_courses:
                if url.endswith(f"id={course_id}"):
                    course_title = title
                    break

            print(f"[INFO] Scanning recordings for course: {course_title} (ID: {course_id})")

            page = self.page
            base_url = f"https://moodle.bgu.ac.il/moodle/blocks/video/videoslist.php?courseid={course_id}"
            await page.goto(base_url)
            await page.wait_for_timeout(1000)
            html = await page.content()
            page_numbers = re.findall(r'data-page-number="(\d+)"', html)
            total_pages = max([int(p) for p in page_numbers] or [1])
            print(f"[INFO] Total pages detected: {total_pages}")

            for page_index in range(total_pages):
                url = f"{base_url}&page={page_index}" if page_index > 0 else base_url
                print(f"[INFO] Navigating to: {url}")
                await page.goto(url)
                await page.wait_for_timeout(1000)

                try:
                    await page.wait_for_selector("#videoslist_table", timeout=3000)
                except Exception as e:
                    print(f"[WARN] Table not found on page {page_index + 1} - Moodle frontend may have changed: {e}")
                    await self.save_error_screenshot("videoslist_table", page)
                    continue

                rows = await page.locator("#videoslist_table tbody tr").all()
                valid_rows = [row for row in rows if "emptyrow" not in (await row.get_attribute("class") or "")]

                for row in valid_rows:
                    try:
                        title = (await row.locator("td.c1").inner_text()).strip()
                        owner = (await row.locator("td.c4").inner_text()).strip()
                        if owner not in uploaders:
                            continue
                        href = await row.locator("td.c0 a").get_attribute("href")
                        if not href:
                            continue
                        full_url = href.lstrip("/")
                        recordings.append((course_title, title, owner, full_url))
                    except Exception as e:
                        print(f"[WARN] Failed to extract row: {e}")

        print(f"[INFO] Total recordings to download: {len(recordings)}")
        self.total_recordings = len(recordings)
        self.root.after(0, self.hide_loading)
        self.root.after(0, lambda: self.progress.config(maximum=max(len(recordings), 1)))
        self.root.after(0, lambda: self.progress_status.config(
            text=f"הורדו 0 מתוך {self.total_recordings} הקלטות"))

        # קביעת שמות קבצים מראש (סדרתית) כדי למנוע התנגשות שמות בין הורדות מקביליות
        tasks = []
        used_paths = set()
        for course_title, title, owner, video_page_url in recordings:
            course_folder = os.path.join(DOWNLOADS_DIR, sanitize_filename(course_title))
            os.makedirs(course_folder, exist_ok=True)
            base_name = f"{sanitize_filename(title)} ! {sanitize_filename(owner)}"
            file_path = get_unique_filename(course_folder, base_name, used_paths)
            tasks.append(self.download_recording(title, owner, video_page_url, file_path))

        self.completed_downloads = 0
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

        async def limited(task):
            async with semaphore:
                await task

        await asyncio.gather(*(limited(t) for t in tasks))

        self.root.after(0, self.on_downloads_finished)

    async def download_recording(self, title, owner, video_page_url, file_path):
        print(f"[INFO] Downloading: {title} by {owner} | URL: {video_page_url}")
        self.root.after(0, lambda t=title: self.progress_file.config(text=f"מוריד: {t}"))
        page = None
        try:
            # דף נפרד לכל הורדה כדי לאפשר הורדות מקביליות על אותו Session
            page = await self.context.new_page()
            await page.goto(video_page_url)
            await page.wait_for_timeout(1000)
            try:
                await page.wait_for_selector("video source", timeout=5000, state="attached")
            except Exception as e:
                print(f"[WARN] 'video source' selector failed for {title} - Moodle frontend may have changed: {e}")
                await self.save_error_screenshot("video_source", page)
                raise
            video_url = await page.locator("video source").get_attribute("src")

            if not video_url:
                raise Exception("No video src found")

            await self.download_mp4(video_url, file_path)

        except Exception as e:
            print(f"[ERROR] Failed to download {title}: {e}")
        finally:
            if page:
                await page.close()

        self.completed_downloads += 1

        def update_progress(v=self.completed_downloads):
            self.progress.config(value=v)
            self.progress_status.config(text=f"הורדו {v} מתוך {self.total_recordings} הקלטות")

        self.root.after(0, update_progress)

    def on_downloads_finished(self):
        self.clean_up()
        self.show_steps(5)
        Label(self.root, text="✓", font=(FONT, 40, "bold"), bg=LIGHT_BLUE, fg=ORANGE).pack(pady=(14, 0))
        Label(self.root, text="ההורדה הושלמה!", font=(FONT, 18, "bold"),
              bg=LIGHT_BLUE, fg=DARK_BLUE).pack(pady=2)
        Label(self.root, text=f"{self.total_recordings} הקלטות נשמרו בתיקיית ההורדות",
              font=(FONT, 12), bg=LIGHT_BLUE, fg=MUTED_BLUE).pack()
        ttk.Button(self.root, text="פתח את תיקיית ההורדות", style="Primary.TButton", cursor="hand2",
                   command=self.open_downloads_folder).pack(pady=(24, 6))
        ttk.Button(self.root, text="חזרה למסך הקורסים", style="Secondary.TButton", cursor="hand2",
                   command=lambda: self.show_courses_screen(self.all_courses)).pack()

    def open_downloads_folder(self):
        folder = os.path.abspath(DOWNLOADS_DIR)
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except Exception as e:
            print(f"[ERROR] Failed to open downloads folder: {e}")
            messagebox.showerror("שגיאה", f"לא ניתן לפתוח את התיקייה:\n{folder}")

    async def download_mp4(self, url, output_path):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(output_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            print(f"[SAVED] File saved to: {output_path}")
        except Exception as e:
            print(f"[ERROR] Failed to download mp4: {e}")


def main():
    # מודעות DPI לפני יצירת החלון - טקסט חד במסכים עם Scaling
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = Tk()
    app = BGUTubeApp(root)
    root.mainloop()

main()
