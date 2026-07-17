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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

USERNAME = ""
PASSWORD = ""
MOODLE_LOGIN_URL = "https://moodle.bgu.ac.il/moodle/login/index.php"
PROFILE_URL = "https://moodle.bgu.ac.il/moodle/user/profile.php"
MAX_CONCURRENT_DOWNLOADS = 3


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
            self.logo_img = ImageTk.PhotoImage(Image.open(logo_path).resize((180, 180)))
            self.logo = Label(root, image=self.logo_img)
        except:
            self.logo = Label(root, text="BGU Tube", font=("Arial", 24, "bold"))
        self.logo.pack(pady=10)

        self.user_label = Label(root, text="שם משתמש", font=("Arial", 12))
        self.user_entry = Entry(root, font=("Arial", 14))
        self.pass_label = Label(root, text="סיסמה", font=("Arial", 12))
        self.pass_entry = Entry(root, show="•", font=("Arial", 14))

        try:
            from Media.LoginInfo import USERNAME, PASSWORD
            self.user_entry.insert(0, USERNAME)
            self.pass_entry.insert(0, PASSWORD)
        except:
            pass

        self.login_btn = Button(root, text="התחבר", font=("Arial", 14), command=self.on_login)

        self.course_frame = Frame(root)
        self.canvas = Canvas(self.course_frame, bg="white")
        self.scrollable_frame = Frame(self.canvas, bg="white")
        self.scrollbar = Scrollbar(self.course_frame, orient=VERTICAL, command=self.canvas.yview)

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.log_out = Button(self.root, text="התנתק", font=("Arial", 14), command=self.logout)
        self.your_courses = Label(self.root, text="הקורסים שלך:", font=("Arial", 16))
        self.course_count = Label(self.root, text="", font=("Arial", 12))

        self.select_all_var = IntVar()
        self.select_all_chk = Checkbutton(self.root, text="בחר/י את כל הקורסים", variable=self.select_all_var,
                                          font=("Arial", 12), command=self.toggle_select_all)

        self.show_selected_btn = Button(self.root, text="הצג קורסים שנבחרו", font=("Arial", 12),
                                        command=self.show_selected_courses, state=DISABLED)

        self.go_to_uploaders_btn = Button(self.root, text="עבור לבחירת מרצים", font=("Arial", 12),
                                          command=self.go_to_uploaders_screen, state=DISABLED)

        self.selected_uploaders = {}
        self.download_btn = Button(self.root, text="הורד/י הקלטות", font=("Arial", 12),
                                   command=self.go_to_download_screen, state=DISABLED)

        self.progress = None
        self.download_button = None  # נשתמש בשם ברור יותר לכפתור ההורדה

        self.loading_label = None
        self.loading_bar = None

        self.login_page()

    def login_page(self):
        self.user_label.pack(fill="x", padx=50)
        self.user_entry.pack(pady=5, padx=50, fill="x")
        self.pass_label.pack(fill="x", padx=50)
        self.pass_entry.pack(pady=5, padx=50, fill="x")
        self.login_btn.pack(pady=20)

    def show_loading(self, text):
        self.hide_loading()
        self.loading_label = Label(self.root, text=text, font=("Arial", 12))
        self.loading_label.pack(pady=(10, 0))
        self.loading_bar = ttk.Progressbar(self.root, mode="indeterminate", length=250)
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
            path = os.path.join(BASE_DIR, f"error_{name}.png")
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
            self.root.after(0, lambda err=e: messagebox.showerror("שגיאה", f"התחברות נכשלה: {err}"))
        self.root.after(0, lambda: self.login_btn.config(state=NORMAL))

    def show_courses_screen(self, course_urls):
        self.clean_up()
        self.your_courses.pack(fill="x", padx=50)
        self.select_all_chk.pack()
        self.course_frame.pack(pady=10, padx=20, fill=BOTH, expand=True)

        for title, url in course_urls:
            var = IntVar()
            chk = Checkbutton(self.scrollable_frame, text=title.strip(), variable=var, font=("Arial", 12),
                              anchor="w", command=self.update_download_button_state)
            chk.pack(fill="x", padx=10, pady=2, anchor="w")
            self.course_vars.append((var, (title, url)))

        self.course_count.config(text=f"סהכ קורסים שנמצאו: {len(course_urls)}")
        self.course_count.pack(pady=5)
        self.log_out.pack(pady=10)
        self.show_selected_btn.pack(pady=5)
        self.go_to_uploaders_btn.pack(pady=5)

    def logout(self):
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
        Label(self.root, text="בחר/י מרצים או מתרגלים", font=("Arial", 16)).pack(pady=10)

        uploader_frame = Frame(self.root)
        canvas = Canvas(uploader_frame, bg="white")
        scrollbar = Scrollbar(uploader_frame, orient=VERTICAL, command=canvas.yview)
        inner_frame = Frame(canvas, bg="white")

        canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        uploader_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.download_btn = Button(self.root, text="הורד/י הקלטות", font=("Arial", 12),
                                   state=DISABLED, command=self.go_to_download_screen)
        self.download_btn.pack(pady=5)

        self.show_loading("טוען רשימת מרצים ומתרגלים...")

        def render_course_uploaders(title, course_id, uploaders):
            Label(inner_frame, text=title.strip(), font=("Arial", 14, "bold"), bg="white").pack(anchor="w", pady=(10, 0))
            if not uploaders:
                Label(inner_frame, text="לא נמצאו הקלטות בקורס", font=("Arial", 12), bg="white", fg="red").pack(
                    anchor="w", padx=20)
                return

            # שמירת הבחירה של המרצים
            self.selected_uploaders[course_id] = []

            for name, count in uploaders.items():
                var = IntVar()
                cb = Checkbutton(inner_frame, text=f"{name} ({count} הקלטות)", font=("Arial", 12), anchor="w",
                                 bg="white", variable=var)
                cb.pack(fill="x", anchor="w", padx=20)
                self.uploader_vars.append((var, name, course_id))

                def update_state(v, uploader, cid):
                    if v.get():
                        if uploader not in self.selected_uploaders[cid]:
                            self.selected_uploaders[cid].append(uploader)
                    else:
                        if uploader in self.selected_uploaders[cid]:
                            self.selected_uploaders[cid].remove(uploader)
                    self.download_btn.config(state=NORMAL if any(self.selected_uploaders.values()) else DISABLED)

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

        Label(self.root, text="בחר/י הקלטות להורדה", font=("Arial", 16)).pack(pady=10)

        download_frame = Frame(self.root)
        canvas = Canvas(download_frame, bg="white")
        scrollbar = Scrollbar(download_frame, orient=VERTICAL, command=canvas.yview)
        inner_frame = Frame(canvas, bg="white")

        canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        download_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        print("[INFO] Selecting uploaders for download: ", len(self.selected_uploaders))
        print("[INFO] Selected uploaders: ", self.selected_uploaders)#################################################################################

        # הצגת הקורסים והמרצים שנבחרו
        for course_id, uploaders in self.selected_uploaders.items():
            course_title = ""
            for _, (title, url) in self.selected_courses:
                if url.endswith(f"id={course_id}"):
                    course_title = title
                    break
            Label(inner_frame, text=course_title, font=("Arial", 14, "bold"), bg="white").pack(anchor="w", pady=(10, 0))

            for uploader in uploaders:
                Label(inner_frame, text=uploader, font=("Arial", 12), bg="white").pack(anchor="w", padx=20)

        self.download_button = Button(self.root, text="התחל הורדה", font=("Arial", 14), command=self.start_downloads)
        self.download_button.pack(pady=10)

    def start_downloads(self):
        print("[INFO] Starting downloads...")
        self.download_button.config(state=DISABLED)
        self.progress = Progressbar(self.root, orient=HORIZONTAL, length=400, mode='determinate')
        self.progress.pack(pady=10)
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
        self.root.after(0, self.hide_loading)
        self.root.after(0, lambda: self.progress.config(maximum=max(len(recordings), 1)))

        # קביעת שמות קבצים מראש (סדרתית) כדי למנוע התנגשות שמות בין הורדות מקביליות
        tasks = []
        used_paths = set()
        for course_title, title, owner, video_page_url in recordings:
            course_folder = os.path.join("downloads", sanitize_filename(course_title))
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
        self.root.after(0, lambda v=self.completed_downloads: self.progress.config(value=v))

    def on_downloads_finished(self):
        messagebox.showinfo("הורדה הושלמה", "כל ההקלטות שנבחרו הורדו!")
        self.progress.pack_forget()

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
    root = Tk()
    app = BGUTubeApp(root)
    root.mainloop()

main()
