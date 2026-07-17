import asyncio
import os
import re
from collections import defaultdict
from tkinter import *
from tkinter import messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from playwright.async_api import async_playwright
import nest_asyncio
nest_asyncio.apply()
import yt_dlp
from urllib.parse import urljoin
import aiohttp
import aiofiles
import httpx
from tkinter.ttk import Progressbar
from functools import partial

USERNAME = ""
PASSWORD = ""
MOODLE_LOGIN_URL = "https://moodle.bgu.ac.il/moodle/login/index.php"
PROFILE_URL = "https://moodle.bgu.ac.il/moodle/user/profile.php"

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

        try:
            self.logo_img = ImageTk.PhotoImage(Image.open("../Media/Logo.png").resize((180, 180)))
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

        self.login_page()

    def login_page(self):
        self.user_label.pack(fill="x", padx=50)
        self.user_entry.pack(pady=5, padx=50, fill="x")
        self.pass_label.pack(fill="x", padx=50)
        self.pass_entry.pack(pady=5, padx=50, fill="x")
        self.login_btn.pack(pady=20)

    def clean_up(self):
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
        asyncio.run(self.login_and_fetch_courses())

    async def login_and_fetch_courses(self):
        print("[INFO] Starting Playwright...")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

        try:
            await self.page.goto(MOODLE_LOGIN_URL)
            await self.page.fill('#login_username', USERNAME)
            await self.page.fill('#login_password', PASSWORD)
            await self.page.click("input[type='submit']")
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

        except Exception as e:
            print(f"[ERROR] {e}")
            messagebox.showerror("שגיאה", f"התחברות נכשלה: {e}")
        self.login_btn.config(state=NORMAL)

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

        async def fetch_uploaders_for_selected():
            self.selected_uploaders.clear()
            page = self.page
            for var, (title, url) in self.selected_courses:
                course_id = url.split("id=")[-1]
                print(f"[INFO] Fetching uploaders for course: {title} (ID: {course_id})")
                uploaders = await self.get_course_media_uploaders(page, course_id)
                Label(inner_frame, text=title.strip(), font=("Arial", 14, "bold"), bg="white").pack(anchor="w", pady=(10, 0))
                if not uploaders:
                    Label(inner_frame, text="לא נמצאו הקלטות בקורס", font=("Arial", 12), bg="white", fg="red").pack(
                        anchor="w", padx=20)
                    continue

                def update_download_btn_state():
                    total_selected = sum(1 for v in self.selected_uploaders.values() if v)
                    self.download_btn.config(state=NORMAL if total_selected else DISABLED)

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

        self.root.after(100, lambda: asyncio.run(fetch_uploaders_for_selected()))

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
            except:
                print(f"[WARN] Table not found on page {page_index + 1}")
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
                except:
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
        self.download_btn.config(state=DISABLED)
        self.progress = Progressbar(self.root, orient=HORIZONTAL, length=400, mode='determinate')
        self.progress.pack(pady=10)
        self.root.after(100, lambda: asyncio.run(self.perform_downloads()))

    async def perform_downloads(self):
        total = 0
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
                except:
                    print(f"[WARN] Table not found on page {page_index + 1}")
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
        self.progress["maximum"] = len(recordings)

        for i, (course_title, title, owner, video_page_url) in enumerate(recordings, 1):
            print(f"[INFO] Downloading: {title} by {owner} | URL: {video_page_url}")
            try:
                await self.page.goto(video_page_url)
                await self.page.wait_for_timeout(1000)
                await self.page.wait_for_selector("video source", timeout=5000, state="attached")
                video_url = await self.page.locator("video source").get_attribute("src")

                if not video_url:
                    raise Exception("No video src found")

                def get_unique_filename(folder, base_name, extension=".mp4"):
                    i = 0
                    candidate = f"{base_name}{extension}"
                    while os.path.exists(os.path.join(folder, candidate)):
                        i += 1
                        candidate = f"{base_name} ({i}){extension}"
                    return os.path.join(folder, candidate)

                # ניקוי שם ההקלטה והמרצה
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
                safe_owner = re.sub(r'[\\/*?:"<>|]', "", owner).strip()

                # יצירת נתיב תיקייה
                course_folder = os.path.join("downloads", re.sub(r'[\\/*?:"<>|]', "", course_title).strip())
                os.makedirs(course_folder, exist_ok=True)

                # יצירת שם קובץ ייחודי
                base_name = f"{safe_title} ! {safe_owner}"
                file_path = get_unique_filename(course_folder, base_name)

                await self.download_mp4(video_url, file_path)

            except Exception as e:
                print(f"[ERROR] Failed to download {title}: {e}")

            self.progress["value"] = i
            self.root.update_idletasks()

        messagebox.showinfo("הורדה הושלמה", "כל ההקלטות שנבחרו הורדו!")
        self.progress.pack_forget()

    async def get_course_recordings_by_uploaders(self, page, course_id, selected_uploaders):
        recordings = []
        base_url = f"https://moodle.bgu.ac.il/moodle/blocks/video/videoslist.php?courseid={course_id}"

        await page.goto(base_url)
        await page.wait_for_timeout(1000)
        html = await page.content()
        page_numbers = re.findall(r'data-page-number="(\d+)"', html)
        total_pages = max([int(p) for p in page_numbers] or [1])

        for page_index in range(total_pages):
            url = f"{base_url}&page={page_index}" if page_index > 0 else base_url
            await page.goto(url)
            await page.wait_for_timeout(1000)

            try:
                await page.wait_for_selector("#videoslist_table", timeout=3000)
            except:
                continue

            rows = await page.locator("#videoslist_table tbody tr").all()
            valid_rows = [row for row in rows if "emptyrow" not in (await row.get_attribute("class") or "")]

            for row in valid_rows:
                try:
                    title = (await row.locator("td.c1").inner_text()).strip()
                    owner = (await row.locator("td.c4").inner_text()).strip()
                    link = await row.locator("td.c0 a").get_attribute("href")

                    if owner in selected_uploaders and link:
                        recordings.append((title, link))
                except:
                    continue

        print(f"[INFO] Total recordings to download for course {course_id}: {len(recordings)}")
        return recordings


    async def download_videos_from_course(self, course_id, course_name, selected_uploaders):
        base_url = f"https://moodle.bgu.ac.il/moodle/blocks/video/videoslist.php?courseid={course_id}"
        page = self.page

        print(f"[INFO] Scanning recordings for course: {course_name} (ID: {course_id})")

        await page.goto(base_url)
        await page.wait_for_timeout(1000)

        try:
            await page.wait_for_selector("#videoslist_table", timeout=3000)
        except:
            print(f"[WARN] Table not found for course {course_id}")
            return

        rows = await page.locator("#videoslist_table tbody tr").all()
        valid_rows = [row for row in rows if "emptyrow" not in (await row.get_attribute("class") or "")]
        print(f"[INFO] Found {len(valid_rows)} valid recordings.")

        for row in valid_rows:
            try:
                title = (await row.locator("td.c1").inner_text()).strip()
                owner = (await row.locator("td.c4").inner_text()).strip()
                video_link = await row.locator("td.c0 a").get_attribute("href")

                if owner not in selected_uploaders:
                    continue

                full_video_url = urljoin("https://moodle.bgu.ac.il/moodle/", video_link)
                print(f"[INFO] Downloading: {title} by {owner} | URL: {full_video_url}")

                # צור תיקיית יעד
                course_dir = os.path.join("downloads", course_name)
                os.makedirs(course_dir, exist_ok=True)

                output_path = os.path.join(course_dir, f"{title}.mp4")
                ydl_opts = {
                    'outtmpl': output_path,
                    'quiet': True,
                    'format': 'best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([full_video_url])

                print(f"[DONE] Saved: {output_path}")

            except Exception as e:
                print(f"[ERROR] Failed to process row: {e}")

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

async def download_video_from_page(page, video_url, filename, folder):
    print(f"[INFO] Navigating to video page: {video_url}")
    await page.goto(video_url)
    await page.wait_for_timeout(1000)

    try:
        await page.wait_for_selector("video source", timeout=5000, state="attached")
        video_src = await page.locator("video source").get_attribute("src")
        if not video_src:
            raise Exception("No video source found.")
        print(f"[INFO] Found video source: {video_src}")
    except Exception as e:
        print(f"[ERROR] Could not find video source: {e}")
        return False

    folder_path = os.path.join("downloads", folder)
    os.makedirs(folder_path, exist_ok=True)
    output_path = os.path.join(folder_path, f"{filename}.mp4")

    print(f"[INFO] Downloading video to {output_path}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(video_src) as resp:
                if resp.status != 200:
                    print(f"[ERROR] Failed to download {video_src} - Status {resp.status}")
                    return False
                async with aiofiles.open(output_path, mode='wb') as f:
                    await f.write(await resp.read())
    except Exception as e:
        print(f"[ERROR] Failed to download video: {e}")
        return False

    print(f"[SUCCESS] Downloaded to: {output_path}")
    return True


def main():
    root = Tk()
    app = BGUTubeApp(root)
    root.mainloop()

main()
