import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID
from .audible_service import AudibleService
from .files import Cancelled, UtilityError, destination, natural_key
from .media import convert, dependencies, merge, probe
from .metadata import FIELDS, edit, read_tags, validate_artwork
from .settings import Settings
from .thumbnails import thumbnail

AUDIO_SUFFIXES = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aax", ".aaxc", ".wma", ".aiff"}


def button(label, callback, icon=None):
    result = Gtk.Button(label=label) if not icon else Gtk.Button(icon_name=icon, tooltip_text=label)
    result.connect("clicked", lambda *_: callback())
    return result


def clear(box):
    while child := box.get_first_child():
        box.remove(child)


class TagForm(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window = window
        self.artwork = None
        self.entries = {}
        group = Adw.PreferencesGroup(title="Audiobook metadata")
        labels = {"artist": "Author / Artist", "date": "Publication date", "description": "Description / Summary"}
        for field in FIELDS:
            row = Adw.EntryRow(title=labels.get(field, field.replace("_", " ").title()))
            self.entries[field] = row
            group.add(row)
        self.append(group)
        self.picture = Gtk.Picture(height_request=160, width_request=120, can_shrink=True,
                                   content_fit=Gtk.ContentFit.CONTAIN)
        self.picture.set_alternative_text("Audiobook cover preview")
        self.append(self.picture)
        actions = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        actions.append(button("Choose Cover…", self.choose_cover))
        actions.append(button("Remove Cover", lambda: self.set_art(None)))
        self.append(actions)

    def choose_cover(self):
        self.window.choose(lambda paths: self.import_cover(paths[0]), images=True)

    def import_cover(self, path):
        def loaded(data):
            self.set_art(data)
        def operation(*_):
            if path.stat().st_size > 20 * 1024 * 1024:
                raise UtilityError("Cover images must be no larger than 20 MiB.")
            return validate_artwork(path.read_bytes())[0]
        self.window.work("Loading cover", operation, loaded)

    def set_art(self, data):
        self.artwork = data
        self.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)) if data else None)

    def fill(self, values, art):
        for field, entry in self.entries.items():
            entry.set_text(values.get(field, ""))
        self.set_art(art)

    def values(self):
        return {field: entry.get_text() for field, entry in self.entries.items()}


class Window(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Audiobook Utility", default_width=960, default_height=780)
        self.cancel = threading.Event()
        self.busy = False
        self.last_output = None
        self.tracks = []
        self.convert_paths = []
        self.metadata_path = None
        self.books = []
        self.book_checks = {}
        self.service = AudibleService()
        try:
            self.settings = Settings.load()
            startup_error = None
        except (UtilityError, OSError) as exc:
            self.settings = Settings()
            startup_error = str(exc)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack = Adw.ViewStack(vexpand=True)
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header = Adw.HeaderBar()
        header.set_title_widget(switcher)
        header.pack_end(button("Preferences", self.preferences, "emblem-system-symbolic"))
        outer.append(header)
        outer.append(self.stack)
        bottom_switcher = Adw.ViewSwitcherBar(stack=self.stack)
        bottom_switcher.set_reveal(True)
        # Compact windows use the bottom switcher; both remain keyboard accessible.
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 650sp"))
        breakpoint.add_setter(switcher, "visible", False)
        self.add_breakpoint(breakpoint)
        self.status = Gtk.Label(label="Ready", xalign=0, wrap=True, selectable=True)
        self.progress = Gtk.ProgressBar(show_text=True)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=18,
                         margin_end=18, margin_top=12, margin_bottom=12)
        footer.append(self.status)
        footer.append(self.progress)
        actions = Gtk.Box(spacing=6)
        self.cancel_button = button("Cancel Operation", self.cancel.set)
        self.cancel_button.set_sensitive(False)
        actions.append(self.cancel_button)
        actions.append(button("Open Output Folder", self.open_output))
        actions.append(button("Convert Last Download", self.convert_download))
        footer.append(actions)
        outer.append(footer)
        outer.append(bottom_switcher)
        self.set_content(outer)
        self.add_page(self.audible_page(), "audible", "Audible", "network-server-symbolic")
        self.add_page(self.convert_page(), "convert", "Convert", "audio-x-generic-symbolic")
        self.add_page(self.merge_page(), "merge", "Merge", "view-list-symbolic")
        self.add_page(self.metadata_page(), "metadata", "Metadata", "document-edit-symbolic")
        self.stack.set_visible_child_name("convert")
        self.connect("close-request", self.close_requested)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self.key_pressed)
        self.add_controller(controller)
        if startup_error:
            GLib.idle_add(self.error, startup_error)
        try:
            dependencies()
        except UtilityError as exc:
            GLib.idle_add(self.error, str(exc))

    def key_pressed(self, controller, key, code, state):
        if key == Gdk.KEY_Escape and self.busy:
            self.cancel.set()
            return True
        if key == Gdk.KEY_o and state & Gdk.ModifierType.CONTROL_MASK:
            page = self.stack.get_visible_child_name()
            self.choose(self.import_merge if page == "merge" else self.import_convert, multiple=True)
            return True
        return False

    def close_requested(self, *_):
        if self.busy:
            self.cancel.set()
            self.status.set_text("Canceling operation. Close the window again after it finishes.")
            return True
        return False

    def add_page(self, widget, name, title, icon):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600, margin_start=18,
                          margin_end=18, margin_top=18, margin_bottom=18)
        clamp.set_child(widget)
        scroll.set_child(clamp)
        self.stack.add_titled_with_icon(scroll, name, title, icon)

    def error(self, message):
        dialog = Adw.MessageDialog(transient_for=self, heading="Operation could not finish", body=message)
        dialog.add_response("close", "Close")
        dialog.present()
        return False

    def choose(self, callback, multiple=False, folder=False, images=False):
        if self.busy:
            return
        dialog = Gtk.FileDialog(title="Choose Folder" if folder else "Choose Cover" if images else "Import Audio")
        if images:
            filter = Gtk.FileFilter(name="JPEG and PNG images")
            filter.add_mime_type("image/jpeg")
            filter.add_mime_type("image/png")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(filter)
            dialog.set_filters(filters)
        def finished(obj, result):
            try:
                if folder:
                    files = [obj.select_folder_finish(result)]
                elif multiple:
                    files = list(obj.open_multiple_finish(result))
                else:
                    files = [obj.open_finish(result)]
                paths = [Path(f.get_path()) for f in files if f.get_path()]
                if paths:
                    callback(paths)
            except GLib.Error as exc:
                if not exc.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.error("File selection failed. Choose a local file or directory.")
        if folder:
            dialog.select_folder(self, None, finished)
        elif multiple:
            dialog.open_multiple(self, None, finished)
        else:
            dialog.open(self, None, finished)

    def drop_target(self, widget, callback):
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        def dropped(controller, value, x, y):
            if self.busy:
                return False
            callback([Path(f.get_path()) for f in value.get_files() if f.get_path()])
            return True
        target.connect("drop", dropped)
        widget.add_controller(target)

    def work(self, title, operation, done=lambda *_: None):
        if self.busy:
            self.error("Wait for the current operation to finish or cancel it first.")
            return
        self.busy = True
        self.cancel.clear()
        self.stack.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.status.set_text(title)
        self.progress.set_fraction(0)
        def progress(value, text):
            def update():
                self.progress.set_fraction(value)
                self.status.set_text(text)
            GLib.idle_add(update)
        def worker():
            result, failure = None, None
            try:
                result = operation(self.cancel, progress)
            except Cancelled as exc:
                failure = (str(exc), False)
            except (UtilityError, OSError) as exc:
                failure = (str(exc), True)
            except Exception:
                failure = ("Unexpected operation failure. Check the input and restart the application before retrying.", True)
            def finish():
                self.busy = False
                self.stack.set_sensitive(True)
                self.cancel_button.set_sensitive(False)
                if failure:
                    self.status.set_text(failure[0])
                    if failure[1]:
                        self.error(failure[0])
                else:
                    self.progress.set_fraction(1)
                    self.status.set_text("Operation complete")
                    done(result)
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=False).start()

    def open_output(self):
        path = self.last_output.parent if self.last_output else Path(self.settings.output).expanduser()
        try:
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (GLib.Error, ValueError):
            self.error("The output folder cannot be opened. Complete an operation or select an existing directory.")

    def convert_download(self):
        if self.last_output and self.last_output.exists():
            self.stack.set_visible_child_name("convert")
            self.import_convert([self.last_output])
        else:
            self.error("Download an audiobook first.")

    def format_picker(self):
        dropdown = Gtk.DropDown.new_from_strings(["M4B (AAC)", "MP3"])
        dropdown.set_selected(0 if self.settings.format == "m4b" else 1)
        dropdown.set_tooltip_text("Output format; M4B supports portable audiobook chapters")
        return dropdown

    def convert_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label="Convert audiobooks", xalign=0, css_classes=["title-1"]))
        box.append(Gtk.Label(label="Import or drop local audio. Original files are always preserved.", xalign=0, wrap=True))
        actions = Gtk.Box(spacing=6)
        actions.append(button("Import Files…", lambda: self.choose(self.import_convert, multiple=True)))
        actions.append(button("Clear", lambda: (self.convert_paths.clear(), clear(self.convert_list))))
        self.convert_format = self.format_picker()
        actions.append(self.convert_format)
        box.append(actions)
        self.convert_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self.convert_list)
        start = button("Convert Imported Files", self.start_convert)
        start.add_css_class("suggested-action")
        box.append(start)
        self.drop_target(box, self.import_convert)
        return box

    def import_convert(self, paths):
        def inspect(cancel, progress):
            result = []
            for path in paths:
                if cancel.is_set():
                    raise Cancelled("Import canceled.")
                if path.suffix.lower() in {".aax", ".aaxc"}:
                    result.append((path, None))
                else:
                    result.append((path, probe(path)))
            return result
        def done(items):
            for path, info in items:
                if path in self.convert_paths:
                    continue
                self.convert_paths.append(path)
                text = "Protected Audible input; account license required" if info is None else (
                    f"{info.codec} · {info.duration / 60:.1f} min · {info.bitrate // 1000} kb/s · "
                    f"{info.sample_rate} Hz · {info.channels} channel(s) · {info.size / 1048576:.1f} MiB · {len(info.chapters)} chapters")
                row = Adw.ActionRow(title=path.name, subtitle=text)
                self.convert_list.append(row)
        self.work("Inspecting audio", inspect, done)

    def start_convert(self):
        paths = list(self.convert_paths)
        if not paths:
            self.error("Import at least one audio file.")
            return
        suffix = ".m4b" if self.convert_format.get_selected() == 0 else ".mp3"
        settings = self.settings
        def operation(cancel, progress):
            outputs = []
            for index, source in enumerate(paths):
                options = self.service.input_options(source)
                target = destination(Path(settings.output), source.stem, suffix, settings.conflict)
                convert(source, target, cancel, lambda p, s, i=index: progress((i + p) / len(paths), s),
                        settings.aac_bitrate if suffix == ".m4b" else settings.mp3_bitrate, options)
                outputs.append(target)
            return outputs
        self.work("Converting audio", operation, lambda outputs: self.completed(outputs[-1]))

    def completed(self, path):
        self.last_output = path
        self.status.set_text(f"Saved: {path}")

    def merge_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label="Merge chapter files", xalign=0, css_classes=["title-1"]))
        actions = Gtk.Box(spacing=6)
        actions.append(button("Import Files…", lambda: self.choose(self.import_merge, multiple=True)))
        actions.append(button("Import Folder…", lambda: self.choose(self.import_folder, folder=True)))
        actions.append(button("Natural Sort", self.sort_tracks))
        box.append(actions)
        self.track_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self.track_list)
        self.total_label = Gtk.Label(label="No tracks imported", xalign=0)
        box.append(self.total_label)
        self.merge_title = Adw.EntryRow(title="Output filename (without extension)", text="Audiobook")
        box.append(self.merge_title)
        self.merge_format = self.format_picker()
        box.append(self.merge_format)
        self.chapter_check = Gtk.CheckButton(label="Use each track as an M4B chapter", active=self.settings.chapters)
        box.append(self.chapter_check)
        box.append(Gtk.Label(label="MP3 output is one continuous track; portable chapter support is less consistent than M4B.", xalign=0, wrap=True, css_classes=["dim-label"]))
        self.merge_tags = TagForm(self)
        expander = Gtk.Expander(label="Finished audiobook metadata and cover")
        expander.set_child(self.merge_tags)
        box.append(expander)
        start = button("Merge Audiobook", self.start_merge)
        start.add_css_class("suggested-action")
        box.append(start)
        self.drop_target(box, self.import_merge)
        return box

    def import_folder(self, paths):
        # Directory scanning is part of the worker import, never a GTK-thread traversal.
        self.import_merge(paths)

    def import_merge(self, paths):
        def inspect(cancel, progress):
            expanded = []
            for path in paths:
                if path.is_dir():
                    expanded.extend(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)
                else:
                    expanded.append(path)
            result = []
            for path in sorted(expanded, key=natural_key):
                if cancel.is_set():
                    raise Cancelled("Import canceled.")
                info = probe(path)
                result.append({"path": path, "info": info, "title": info.tags.get("title", path.stem)})
            return result
        def done(tracks):
            known = {t["path"] for t in self.tracks}
            self.tracks.extend(t for t in tracks if t["path"] not in known)
            self.sort_tracks()
        self.work("Inspecting chapter files", inspect, done)

    def sort_tracks(self):
        self.tracks.sort(key=lambda t: natural_key(t["path"]))
        self.render_tracks()

    def render_tracks(self):
        clear(self.track_list)
        for index, track in enumerate(self.tracks):
            row = Adw.EntryRow(title=f"{index + 1}. {track['path'].name} · {track['info'].duration:.2f} s", text=track["title"])
            row.connect("changed", lambda entry, t=track: t.update(title=entry.get_text()))
            for delta, label, icon in [(-1, "Move up", "go-up-symbolic"), (1, "Move down", "go-down-symbolic")]:
                action = button(label, lambda i=index, d=delta: self.move_track(i, d), icon)
                action.set_sensitive(0 <= index + delta < len(self.tracks))
                row.add_suffix(action)
            row.add_suffix(button("Remove track", lambda i=index: self.remove_track(i), "list-remove-symbolic"))
            self.track_list.append(row)
        self.total_label.set_text(f"{len(self.tracks)} tracks · {sum(t['info'].duration for t in self.tracks) / 60:.2f} minutes total")

    def move_track(self, index, delta):
        self.tracks[index], self.tracks[index + delta] = self.tracks[index + delta], self.tracks[index]
        self.render_tracks()

    def remove_track(self, index):
        self.tracks.pop(index)
        self.render_tracks()

    def start_merge(self):
        if not self.tracks:
            self.error("Import at least one chapter file.")
            return
        tracks = list(self.tracks)
        suffix = ".m4b" if self.merge_format.get_selected() == 0 else ".mp3"
        title = self.merge_title.get_text()
        tags = self.merge_tags.values()
        tags["title"] = tags["title"] or title
        art = self.merge_tags.artwork
        chapters = self.chapter_check.get_active()
        settings = self.settings
        def operation(cancel, progress):
            target = destination(Path(settings.output), title, suffix, settings.conflict)
            return merge([t["path"] for t in tracks], target, cancel, progress,
                         titles=[t["title"] for t in tracks], chapters=chapters,
                         bitrate=settings.aac_bitrate if suffix == ".m4b" else settings.mp3_bitrate,
                         tags=tags, artwork=art,
                         temporary_dir=Path(settings.temporary) if settings.temporary else None)
        self.work("Merging chapter files", operation, self.completed)

    def metadata_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label="Edit metadata and artwork", xalign=0, css_classes=["title-1"]))
        box.append(button("Open Audiobook…", lambda: self.choose(lambda p: self.open_metadata(p[0]))))
        self.metadata_label = Gtk.Label(label="Open an MP3, M4A or M4B file", xalign=0, wrap=True)
        box.append(self.metadata_label)
        self.tag_form = TagForm(self)
        box.append(self.tag_form)
        actions = Gtk.Box(spacing=6)
        actions.append(button("Save Changes", self.save_metadata))
        actions.append(button("Restore from File", lambda: self.open_metadata(self.metadata_path) if self.metadata_path else None))
        box.append(actions)
        self.drop_target(box, lambda paths: self.open_metadata(paths[0]) if paths else None)
        return box

    def open_metadata(self, path):
        def done(result):
            self.metadata_path = path
            self.metadata_label.set_text(str(path))
            self.tag_form.fill(*result)
        self.work("Reading metadata", lambda *_: read_tags(path), done)

    def save_metadata(self):
        if not self.metadata_path:
            self.error("Open an audiobook before saving tags.")
            return
        path, tags, art = self.metadata_path, self.tag_form.values(), self.tag_form.artwork
        self.work("Saving metadata", lambda *_: edit(path, tags, art), self.completed)

    def audible_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label="Audible.com library", xalign=0, css_classes=["title-1"]))
        self.account_label = Gtk.Label(label="US marketplace · Connect or refresh to check your saved session", xalign=0, wrap=True)
        box.append(self.account_label)
        actions = Gtk.Box(spacing=6)
        actions.append(button("Connect…", self.connect_audible))
        actions.append(button("Disconnect", lambda: self.work("Disconnecting", lambda *_: self.service.disconnect(), self.disconnected)))
        actions.append(button("Refresh Library", self.refresh_library))
        box.append(actions)
        self.search = Gtk.SearchEntry(placeholder_text="Search title or author")
        self.search.connect("search-changed", lambda *_: self.render_books())
        box.append(self.search)
        self.book_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self.book_list)
        actions = Gtk.Box(spacing=6)
        actions.append(button("Select Visible", lambda: self.select_books(True)))
        actions.append(button("Clear Selection", lambda: self.select_books(False)))
        actions.append(button("Download Selected / Retry", self.download_selected))
        box.append(actions)
        return box

    def connect_audible(self):
        def callback(url):
            ready = threading.Event()
            result = []
            def prompt():
                try:
                    Gio.AppInfo.launch_default_for_uri(url, None)
                except GLib.Error:
                    self.error("Could not open the system browser. Configure a default browser and try again.")
                    ready.set()
                    return
                dialog = Adw.MessageDialog(transient_for=self, heading="Finish sign-in in your browser",
                    body="Complete Amazon sign-in and any security checks in your browser. The final page may report an error. Paste its complete maplanding URL below. This URL contains a temporary authorization code.")
                entry = Gtk.PasswordEntry(show_peek_icon=True)
                entry.set_tooltip_text("Final Amazon redirect URL (sensitive)")
                dialog.set_extra_child(entry)
                dialog.add_response("cancel", "Cancel")
                dialog.add_response("connect", "Connect")
                def response(obj, choice):
                    if choice == "connect":
                        result.append(entry.get_text())
                    entry.set_text("")
                    ready.set()
                dialog.connect("response", response)
                dialog.present()
            GLib.idle_add(prompt)
            while not ready.wait(0.1):
                if self.cancel.is_set():
                    raise Cancelled("Sign-in canceled.")
            if not result:
                raise Cancelled("Sign-in canceled.")
            return result[0]
        self.work("Connecting to Audible", lambda *_: self.service.connect(callback),
                  lambda *_: self.account_label.set_text("Connected to Audible.com · Refresh your library"))

    def disconnected(self, *_):
        self.books = []
        self.book_checks.clear()
        clear(self.book_list)
        self.account_label.set_text("Disconnected · Saved session and media licenses removed from keyring")

    def library_loaded(self, books):
        self.books = books
        self.account_label.set_text(f"Connected · {len(books)} titles")
        self.render_books()

    def refresh_library(self):
        def operation(cancel, progress):
            books = self.service.library(cancel)
            for index, book in enumerate(books):
                if cancel.is_set():
                    raise Cancelled("Library refresh canceled.")
                book.local_path = self.service.receipts.verified(book.asin, cancel)
                book.cover_data = thumbnail(book.cover)
                progress((index + 1) / max(1, len(books)), "Loading covers and verifying local downloads")
            return books
        self.work("Retrieving library", operation, self.library_loaded)

    def render_books(self):
        clear(self.book_list)
        query = self.search.get_text().casefold()
        for book in self.books:
            if query not in f"{book.title} {book.author}".casefold():
                continue
            row = Adw.ActionRow(title=book.title, subtitle=f"{book.author} · {book.minutes} min" + (" · Download verified" if book.local_path else "") + (" · Unavailable for offline download" if not book.downloadable else ""))
            if book.cover_data:
                picture = Gtk.Picture(paintable=Gdk.Texture.new_from_bytes(GLib.Bytes.new(book.cover_data)),
                                      width_request=48, height_request=64,
                                      content_fit=Gtk.ContentFit.CONTAIN)
                picture.set_alternative_text(f"Cover of {book.title}")
                row.add_prefix(picture)
            check = Gtk.CheckButton(active=self.book_checks.get(book.asin, False), tooltip_text=f"Select {book.title}")
            check.set_sensitive(book.downloadable)
            check.connect("toggled", lambda widget, asin=book.asin: self.book_checks.update({asin: widget.get_active()}))
            row.add_prefix(check)
            self.book_list.append(row)

    def select_books(self, active):
        query = self.search.get_text().casefold()
        for book in self.books:
            if query in f"{book.title} {book.author}".casefold() and book.downloadable:
                self.book_checks[book.asin] = active
        self.render_books()

    def download_selected(self):
        books = [b for b in self.books if self.book_checks.get(b.asin)]
        if not books:
            self.error("Select available titles to download.")
            return
        def operation(cancel, progress):
            outputs = []
            failures = []
            for index, book in enumerate(books):
                try:
                    path = self.service.download_book(book, Path(self.settings.downloads), cancel,
                        lambda p, s, i=index, b=book: progress((i + p) / len(books), f"{b.title}: {s}"))
                    outputs.append(path)
                    def completed_book(b=book, p=path):
                        b.local_path = p
                        self.book_checks[b.asin] = False
                        self.completed(p)
                        self.render_books()
                    GLib.idle_add(completed_book)
                except Cancelled:
                    raise
                except UtilityError as exc:
                    failures.append(f"{book.title}: {exc}")
            if failures:
                raise UtilityError("Some downloads could not finish. Completed titles were preserved; retry the selected failures.\n\n" + "\n".join(failures))
            return outputs
        self.work("Downloading selected books", operation, lambda outputs: self.completed(outputs[-1]))

    def preferences(self):
        if self.busy:
            return
        dialog = Adw.PreferencesWindow(transient_for=self, modal=True, title="Preferences", default_width=650, default_height=700)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Files and audio")
        rows = {}
        for field, title in [("downloads", "Audible download directory"), ("output", "Converted audiobook directory"), ("temporary", "Temporary directory (empty uses system default)")]:
            row = Adw.EntryRow(title=title, text=getattr(self.settings, field))
            def select(row=row):
                self.choose(lambda paths: row.set_text(str(paths[0])), folder=True)
            row.add_suffix(button("Choose directory", select, "folder-open-symbolic"))
            rows[field] = row
            group.add(row)
        choices = {}
        for field, title, values in [
            ("format", "Default conversion format", ["m4b", "mp3"]),
            ("mp3_bitrate", "MP3 bitrate (kb/s)", [64, 96, 128, 192, 256, 320]),
            ("aac_bitrate", "M4B AAC bitrate (kb/s)", [64, 96, 128, 192, 256]),
            ("conflict", "Existing filename behavior", ["rename", "fail"]),
        ]:
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new([str(v) for v in values]))
            row.set_selected(values.index(getattr(self.settings, field)))
            choices[field] = (row, values)
            group.add(row)
        chapters = Adw.SwitchRow(title="Generate merge chapters by default", active=self.settings.chapters)
        group.add(chapters)
        group.add(Adw.ActionRow(title="Temporary files", subtitle="Removed after success, failure or cancellation"))
        group.add(Adw.ActionRow(title="Appearance", subtitle="Follows GNOME light/dark mode and system accent"))
        def save():
            try:
                settings = Settings(**{k: r.get_text() for k, r in rows.items()},
                    **{k: values[row.get_selected()] for k, (row, values) in choices.items()}, chapters=chapters.get_active())
                settings.save()
                self.settings = settings
                dialog.close()
            except (UtilityError, OSError) as exc:
                self.error(str(exc))
        group.add(button("Save Preferences", save))
        page.add(group)
        dialog.add(page)
        dialog.present()


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()
