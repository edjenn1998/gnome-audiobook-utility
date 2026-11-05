import threading
from concurrent.futures import ThreadPoolExecutor
import weakref
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import APP_ID
from .audible_service import AudibleService
from .diagnostics import record_exception
from .files import Cancelled, UtilityError, destination, natural_key
from .media import convert, dependencies, merge, probe
from .metadata import FIELDS, edit, prepare_preview, read_tags, validate_artwork
from .progress import ProgressDispatch
from .settings import Settings
from .thumbnails import thumbnail

AUDIO_SUFFIXES = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aax", ".aaxc", ".wma", ".aiff"}


def button(label, callback, icon=None):
    result = Gtk.Button(label=label) if not icon else Gtk.Button(icon_name=icon, tooltip_text=label)
    result.update_property([Gtk.AccessibleProperty.LABEL], [label])
    result.connect("clicked", lambda *_: callback())
    return result


def clear(box):
    while child := box.get_first_child():
        box.remove(child)


def row_list():
    return Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])


class SummaryEditor(Gtk.TextView):
    def __init__(self):
        super().__init__(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12, bottom_margin=12,
                         left_margin=12, right_margin=12)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Description / Summary"])

    def set_text(self, value):
        self.get_buffer().set_text(value)

    def get_text(self):
        buffer = self.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)


class LibraryItem(GObject.Object):
    def __init__(self, book):
        super().__init__()
        self.book = book


class TagForm(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window = window
        self.artwork = None
        self._art_generation = 0
        self._preview_future = None
        self.entries = {}
        group = Adw.PreferencesGroup(title="Audiobook metadata")
        labels = {"artist": "Author / Artist", "date": "Publication date", "description": "Description / Summary"}
        for field in FIELDS:
            if field == "description":
                continue
            row = Adw.EntryRow(title=labels.get(field, field.replace("_", " ").title()))
            self.entries[field] = row
            group.add(row)
        self.append(group)
        self.append(Gtk.Label(label="Description / Summary", xalign=0))
        self.entries["description"] = SummaryEditor()
        summary = Gtk.ScrolledWindow(min_content_height=140, max_content_height=240,
                                     propagate_natural_height=True,
                                     hscrollbar_policy=Gtk.PolicyType.NEVER)
        summary.set_child(self.entries["description"])
        self.append(Gtk.Frame(child=summary))
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
        def loaded(result):
            self.set_art(result[0], result[1])
        def operation(*_):
            if path.stat().st_size > 20 * 1024 * 1024:
                raise UtilityError("Cover images must be no larger than 20 MiB.")
            data = validate_artwork(path.read_bytes())[0]
            return data, prepare_preview(data)
        self.window.work("Loading cover", operation, loaded)

    def set_art(self, data, preview=None):
        self._art_generation += 1
        if self._preview_future:
            self._preview_future.cancel()
        self.artwork = data
        self.picture.set_paintable(None)
        if data:
            if preview is not None:
                self.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(preview)))
            else:
                self.window.submit_preview(self, data, self._art_generation)

    def fill(self, values, art, preview=None):
        for field, entry in self.entries.items():
            entry.set_text(values.get(field, ""))
        self.set_art(art, preview)

    def values(self):
        return {field: entry.get_text() for field, entry in self.entries.items()}


class Window(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Audiobook Utility", default_width=960, default_height=780)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.cancel = threading.Event()
        self.busy = False
        self.last_output = None
        self.last_download = None
        self.tracks = []
        self.convert_paths = []
        self.metadata_path = None
        self.books = []
        self.book_checks = {}
        self.login_window = None
        self._closing = False
        self._operation_id = 0
        self._preview_pool = None
        self._library_widgets_created = 0
        self.connect("unrealize", self.cleanup_resources)
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
        header.pack_end(button("About Audiobook Utility", self.about, "help-about-symbolic"))
        outer.append(header)
        outer.append(self.stack)
        bottom_switcher = Adw.ViewSwitcherBar(stack=self.stack)
        bottom_switcher.set_reveal(False)
        # Navigation moves to the bottom in compact windows.
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 650sp"))
        breakpoint.add_setter(switcher, "visible", False)
        breakpoint.add_setter(bottom_switcher, "reveal", True)
        self.compact_breakpoint = breakpoint
        self.add_breakpoint(breakpoint)
        self.status = Gtk.Label(label="Ready", xalign=0, wrap=True, selectable=True)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.update_property([Gtk.AccessibleProperty.LABEL], ["Operation progress"])
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=18,
                         margin_end=18, margin_top=12, margin_bottom=12)
        footer.append(self.status)
        footer.append(self.progress)
        actions = self.adaptive_actions()
        self.cancel_button = button("Cancel Operation", self.cancel.set)
        self.cancel_button.set_sensitive(False)
        actions.append(self.cancel_button)
        actions.append(button("Open Output Folder", self.open_output))
        self.convert_download_button = button("Convert Last Download", self.convert_download)
        self.convert_download_button.set_sensitive(False)
        actions.append(self.convert_download_button)
        footer.append(actions)
        outer.append(footer)
        outer.append(bottom_switcher)
        self.set_content(outer)
        self.add_page(self.audible_page(), "audible", "Audible", "network-server-symbolic", scrollable=False)
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
            if page == "metadata":
                self.choose(lambda paths: self.open_metadata(paths[0]))
            else:
                self.choose(self.import_merge if page == "merge" else self.import_convert, multiple=True)
            return True
        return False

    def adaptive_actions(self):
        box = Gtk.Box(spacing=6)
        self.compact_breakpoint.add_setter(box, "orientation", Gtk.Orientation.VERTICAL)
        return box

    def submit_preview(self, form, data, generation):
        if self._closing:
            return
        if self._preview_pool is None:
            self._preview_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cover-preview")
        window_ref, form_ref = weakref.ref(self), weakref.ref(form)
        future = self._preview_pool.submit(prepare_preview, data)
        form._preview_future = future
        def completed(task):
            if task.cancelled():
                return
            try:
                preview, failure = task.result(), None
            except Exception as error:
                preview, failure = None, error
            def apply():
                window, target = window_ref(), form_ref()
                if window is None or target is None or window._closing or target._art_generation != generation:
                    return False
                if failure:
                    record_exception(failure)
                    window.error("The cover preview could not be prepared. Choose a valid JPEG or PNG image.")
                else:
                    target.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(preview)))
                return False
            GLib.idle_add(apply)
        future.add_done_callback(completed)

    def cleanup_resources(self, *_):
        self._closing = True
        self.cancel.set()
        if self._preview_pool:
            self._preview_pool.shutdown(wait=False, cancel_futures=True)
            self._preview_pool = None
        if self.login_window:
            self.login_window.close_requested()
            self.login_window = None

    def close_requested(self, *_):
        if self.busy:
            self.cancel.set()
            self.status.set_text("Canceling operation. Close the window again after it finishes.")
            return True
        return False

    def add_page(self, widget, name, title, icon, scrollable=True):
        if not scrollable:
            self.stack.add_titled_with_icon(widget, name, title, icon)
            return
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600, margin_start=18,
                          margin_end=18, margin_top=18, margin_bottom=18)
        clamp.set_child(widget)
        scroll.set_child(clamp)
        self.stack.add_titled_with_icon(scroll, name, title, icon)

    def error(self, message):
        dialog = Adw.AlertDialog(heading="Operation could not finish", body=message, body_use_markup=False)
        dialog.add_response("close", "Close")
        dialog.present(self)
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
        self._operation_id += 1
        operation_id = self._operation_id
        self.cancel.clear()
        self.stack.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.update_library_actions()
        self.status.set_text(title)
        self.progress.set_fraction(0)
        def update(value, text):
            if not self._closing and self.busy and self._operation_id == operation_id:
                self.progress.set_fraction(value)
                self.status.set_text(text)
        progress = ProgressDispatch(update, GLib.idle_add)
        def worker():
            result, failure = None, None
            try:
                result = operation(self.cancel, progress)
            except Cancelled as exc:
                failure = (str(exc), False)
            except (UtilityError, OSError) as exc:
                record_exception(exc)
                failure = (str(exc), True)
            except Exception as exc:
                record_exception(exc)
                failure = ("Unexpected operation failure. Check the input and restart the application before retrying.", True)
            def finish():
                progress.close()
                self.busy = False
                if self._closing:
                    return False
                self.stack.set_sensitive(True)
                self.cancel_button.set_sensitive(False)
                if failure:
                    self.status.set_text(failure[0])
                    if failure[1]:
                        self.error(failure[0])
                else:
                    self.progress.set_fraction(1)
                    self.status.set_text("Operation complete")
                    try:
                        done(result)
                    except (UtilityError, OSError, GLib.Error) as exc:
                        record_exception(exc)
                        self.error("The operation finished, but its result could not be displayed. Check the output file and artwork format.")
                self.update_library_actions()
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=False).start()

    def open_output(self):
        path = self.last_output.parent if self.last_output else Path(self.settings.output).expanduser()
        try:
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (GLib.Error, ValueError):
            self.error("The output folder cannot be opened. Complete an operation or select an existing directory.")

    def convert_download(self):
        if self.last_download and self.last_download.exists():
            self.stack.set_visible_child_name("convert")
            self.import_convert([self.last_download])
        else:
            self.error("Download an audiobook first.")

    def format_picker(self):
        dropdown = Gtk.DropDown.new_from_strings(["M4B (AAC)", "MP3"])
        dropdown.set_selected(0 if self.settings.format == "m4b" else 1)
        dropdown.set_tooltip_text("Output format; M4B supports portable audiobook chapters")
        dropdown.update_property([Gtk.AccessibleProperty.LABEL], ["Output audio format"])
        return dropdown

    def convert_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label="Convert audiobooks", xalign=0, css_classes=["title-1"]))
        box.append(Gtk.Label(label="Import or drop local audio. Original files are always preserved.", xalign=0, wrap=True))
        actions = self.adaptive_actions()
        actions.append(button("Import Files…", lambda: self.choose(self.import_convert, multiple=True)))
        actions.append(button("Clear", lambda: (self.convert_paths.clear(), clear(self.convert_list))))
        self.convert_format = self.format_picker()
        actions.append(self.convert_format)
        box.append(actions)
        self.convert_list = row_list()
        box.append(self.convert_list)
        start = button("Convert Imported Files", self.start_convert)
        start.add_css_class("suggested-action")
        start.set_halign(Gtk.Align.END)
        box.append(start)
        self.drop_target(box, self.import_convert)
        return box

    def import_convert(self, paths):
        def inspect(cancel, progress):
            result = []
            for path in paths:
                if cancel.is_set():
                    raise Cancelled("Import canceled.")
                progress(0, "Resolving input license and inspecting audio")
                options = self.service.input_options(path, cancel)
                result.append((path, probe(path, options), bool(options)))
            return result
        def done(items):
            for path, info, licensed in items:
                if path in self.convert_paths:
                    continue
                self.convert_paths.append(path)
                text = (
                    f"{info.codec} · {info.duration / 60:.1f} min · {info.bitrate // 1000} kb/s · "
                    f"{info.sample_rate} Hz · {info.channels} channel(s) · {info.size / 1048576:.1f} MiB · {len(info.chapters)} chapters")
                if licensed:
                    text += " · Audible license loaded"
                row = Adw.ActionRow(title=path.name, subtitle=text, use_markup=False)
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
                progress(index / len(paths), "Resolving input license and inspecting audio")
                options = self.service.input_options(source, cancel)
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
        actions = self.adaptive_actions()
        actions.append(button("Import Files…", lambda: self.choose(self.import_merge, multiple=True)))
        actions.append(button("Import Folder…", lambda: self.choose(self.import_folder, folder=True)))
        actions.append(button("Natural Sort", self.sort_tracks))
        box.append(actions)
        self.track_list = row_list()
        box.append(self.track_list)
        self.total_label = Gtk.Label(label="No tracks imported", xalign=0)
        box.append(self.total_label)
        self.merge_title = Adw.EntryRow(title="Output filename (without extension)", text="Audiobook")
        filename_group = Adw.PreferencesGroup()
        filename_group.add(self.merge_title)
        box.append(filename_group)
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
        start.set_halign(Gtk.Align.END)
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
            row = Adw.EntryRow(title=f"{index + 1}. {track['path'].name} · {track['info'].duration:.2f} s", text=track["title"], use_markup=False)
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
        actions = self.adaptive_actions()
        actions.append(button("Save Changes", self.save_metadata))
        actions.append(button("Restore from File", lambda: self.open_metadata(self.metadata_path) if self.metadata_path else None))
        box.append(actions)
        self.drop_target(box, lambda paths: self.open_metadata(paths[0]) if paths else None)
        return box

    def open_metadata(self, path):
        def read(*_):
            values, art = read_tags(path)
            return values, art, prepare_preview(art) if art else None
        def done(result):
            self.metadata_path = path
            self.metadata_label.set_text(str(path))
            self.tag_form.fill(*result)
        self.work("Reading metadata", read, done)

    def save_metadata(self):
        if not self.metadata_path:
            self.error("Open an audiobook before saving tags.")
            return
        path, tags, art = self.metadata_path, self.tag_form.values(), self.tag_form.artwork
        self.work("Saving metadata", lambda cancel, _: edit(path, tags, art, cancel), self.completed)

    def audible_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        header.append(Gtk.Label(label="Audible.com library", xalign=0, css_classes=["title-1"]))
        self.account_label = Gtk.Label(label="US marketplace · Log in or refresh to use your saved session", xalign=0, wrap=True)
        header.append(self.account_label)
        actions = self.adaptive_actions()
        account_actions = Gtk.Box(spacing=6)
        account_actions.append(button("Login to Audible", self.connect_audible))
        account_actions.append(button("Disconnect", lambda: self.work("Disconnecting", lambda *_: self.service.disconnect(), self.disconnected)))
        actions.append(account_actions)
        library_actions = Gtk.Box(spacing=6)
        library_actions.append(button("Refresh Library", self.refresh_library))
        library_actions.append(button("Forget Licenses…", self.confirm_forget_licenses))
        actions.append(library_actions)
        header.append(actions)
        self.search = Gtk.SearchEntry(placeholder_text="Search title or author")
        self.search.connect("search-changed", lambda *_: self.render_books())
        header.append(self.search)
        self.library_toolbar = self.adaptive_actions()
        self.select_visible_button = button("Select Visible", lambda: self.select_books(True))
        self.clear_selection_button = button("Clear Selection", lambda: self.select_books(False))
        self.clear_selection_button.set_tooltip_text("Clear selected titles in the current search")
        self.download_selected_button = button("Download Selected / Retry", self.download_selected)
        self.download_selected_button.add_css_class("suggested-action")
        selection_actions = Gtk.Box(spacing=6)
        selection_actions.append(self.select_visible_button)
        selection_actions.append(self.clear_selection_button)
        self.library_toolbar.append(selection_actions)
        self.library_toolbar.append(self.download_selected_button)
        header.append(self.library_toolbar)
        header_clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600, margin_start=18,
                                 margin_end=18, margin_top=18, margin_bottom=12)
        header_clamp.set_child(header)
        box.append(header_clamp)
        self.library_model = Gio.ListStore.new(LibraryItem)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self.setup_library_item)
        factory.connect("bind", self.bind_library_item)
        factory.connect("unbind", self.unbind_library_item)
        self.book_list = Gtk.ListView(model=Gtk.NoSelection.new(self.library_model), factory=factory,
                                      css_classes=["boxed-list"])
        list_clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600,
                              margin_start=18, margin_end=18, margin_bottom=18)
        list_clamp.set_child(self.book_list)
        self.library_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.library_scroll.set_child(list_clamp)
        box.append(self.library_scroll)
        self.update_library_actions()
        return box

    def connect_audible(self):
        if self.busy:
            return
        from .login_flow import LoginRequest
        from .login_window import LoginWindow

        def callback(url):
            request = LoginRequest(url, self.cancel)
            def prompt():
                if self.cancel.is_set():
                    request.cancel()
                    return
                try:
                    self.login_window = LoginWindow(self, request)
                    self.login_window.present()
                except UtilityError as exc:
                    request.fail(exc)
                except Exception as exc:
                    record_exception(exc)
                    request.fail(UtilityError("The sign-in browser could not start. Check WebKitGTK and try again."))
            GLib.idle_add(prompt)
            return request.wait()
        def close_login():
            if self.login_window:
                self.login_window.finish()
                self.login_window = None
        def operation(cancel, progress):
            try:
                return self.service.connect(callback, cancel)
            finally:
                GLib.idle_add(close_login)
        self.work("Connecting to Audible", operation,
                  lambda *_: self.account_label.set_text("Connected to Audible.com · Credentials saved securely · Refresh your library"))

    def disconnected(self, *_):
        self.books = []
        self.book_checks.clear()
        self.library_model.remove_all()
        self.account_label.set_text("Disconnected · Download licenses kept securely for local conversion")
        self.update_library_actions()

    def confirm_forget_licenses(self):
        if self.busy:
            return
        dialog = Adw.AlertDialog(heading="Permanently forget download licenses?",
            body="Existing protected audiobooks may no longer be convertible. Some titles may not be downloadable again. Ordinary Disconnect keeps these licenses.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("forget", "Permanently Forget Licenses")
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("forget", Adw.ResponseAppearance.DESTRUCTIVE)
        def response(_, choice):
            if choice == "forget":
                self.work("Forgetting download licenses", lambda *_: self.service.forget_media_licenses())
        dialog.connect("response", response)
        self.forget_dialog = dialog
        dialog.present(self)

    def library_loaded(self, books):
        self.books = books
        self.book_checks = {book.asin: bool(self.book_checks.get(book.asin)) for book in books if book.downloadable is True}
        skipped = getattr(self.service, "library_skipped", 0)
        self.account_label.set_text(f"Connected · {len(books)} titles" + (f" · {skipped} invalid entries skipped" if skipped else ""))
        self.render_books()

    def refresh_library(self):
        def operation(cancel, progress):
            books = self.service.library(cancel)
            for index, book in enumerate(books):
                if cancel.is_set():
                    raise Cancelled("Library refresh canceled.")
                book.local_path = self.service.receipts.verified(book.asin, cancel)
                book.cover_data = thumbnail(book.cover, cancel=cancel)
                progress((index + 1) / max(1, len(books)), "Loading covers and verifying local downloads")
            return books
        self.work("Retrieving library", operation, self.library_loaded)

    def render_books(self):
        query = self.search.get_text().casefold()
        items = [LibraryItem(book) for book in self.books if query in f"{book.title} {book.author}".casefold()]
        self.library_model.splice(0, self.library_model.get_n_items(), items)
        self.update_library_actions()

    def setup_library_item(self, factory, item):
        self._library_widgets_created += 1
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        row = Adw.ActionRow(use_markup=False)
        row._book, row._binding = None, False
        row._check = Gtk.CheckButton()
        row._picture = Gtk.Picture(width_request=48, height_request=64, content_fit=Gtk.ContentFit.CONTAIN)
        row.add_prefix(row._check)
        row.add_prefix(row._picture)
        def toggled(check):
            if row._book is not None and not row._binding:
                self.selection_changed(row._book.asin, check.get_active())
        row._check.connect("toggled", toggled)
        box.append(row)
        item.set_child(box)

    def bind_library_item(self, factory, item):
        book = item.get_item().book
        row = item.get_child().get_first_child()
        row._book, row._binding = book, True
        row.set_title(book.title)
        duration = f"{book.minutes} min" if book.minutes is not None else "Unknown duration"
        availability = (" · Eligibility not reported; refresh to check" if book.downloadable is None
                        else " · Unavailable for offline download" if not book.downloadable else "")
        row.set_subtitle(f"{book.author} · {duration}" + (" · Download verified" if book.local_path else "") + availability)
        row._check.set_active(self.book_checks.get(book.asin, False))
        row._check.set_sensitive(book.downloadable is True)
        row._check.update_property([Gtk.AccessibleProperty.LABEL], [f"Select {book.title}"])
        row._check.set_tooltip_text(f"Select {book.title}" if book.downloadable else availability.strip(" ·"))
        row._picture.set_visible(bool(book.cover_data))
        row._picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(book.cover_data)) if book.cover_data else None)
        row._picture.set_alternative_text(f"Cover of {book.title}")
        row._binding = False

    def unbind_library_item(self, factory, item):
        row = item.get_child().get_first_child()
        row._book = None
        row._picture.set_paintable(None)

    def selection_changed(self, asin, active):
        self.book_checks[asin] = active
        self.update_library_actions()

    def update_library_actions(self):
        query = self.search.get_text().casefold()
        visible = [book for book in self.books if book.downloadable
                   and query in f"{book.title} {book.author}".casefold()]
        selected = [book for book in self.books if book.downloadable and self.book_checks.get(book.asin)]
        self.select_visible_button.set_sensitive(not self.busy and any(not self.book_checks.get(b.asin) for b in visible))
        self.clear_selection_button.set_sensitive(not self.busy and any(self.book_checks.get(b.asin) for b in visible))
        self.download_selected_button.set_sensitive(not self.busy and bool(selected))
        self.download_selected_button.set_tooltip_text(f"Download {len(selected)} selected titles, including selections outside the current search. Failed titles stay selected for retry.")
        self.convert_download_button.set_sensitive(not self.busy and self.last_download is not None)

    def select_books(self, active):
        query = self.search.get_text().casefold()
        for book in self.books:
            if query in f"{book.title} {book.author}".casefold() and book.downloadable:
                self.book_checks[book.asin] = active
        self.render_books()

    def download_selected(self):
        books = [b for b in self.books if b.downloadable and self.book_checks.get(b.asin)]
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
                        self.last_download = p
                        self.book_checks[b.asin] = False
                        self.completed(p)
                        self.render_books()
                    GLib.idle_add(completed_book)
                except Cancelled:
                    raise
                except UtilityError as exc:
                    record_exception(exc)
                    failures.append(f"{book.title}: {exc}")
            if failures:
                raise UtilityError("Some downloads could not finish. Completed titles were preserved; retry the selected failures.\n\n" + "\n".join(failures))
            return outputs
        self.work("Downloading selected books", operation, lambda outputs: self.completed(outputs[-1]))

    def preferences(self):
        if self.busy:
            return
        dialog = Adw.PreferencesDialog(title="Preferences", content_width=650, content_height=700)
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
        dialog.present(self)

    def about(self):
        dialog = Adw.AboutDialog(application_name="Audiobook Utility",
            application_icon=APP_ID, version="0.1.0", license_type=Gtk.License.AGPL_3_0_ONLY,
            comments="Convert, merge and tag audiobooks. Free software under the GNU AGPL version 3; no warranty.")
        dialog.add_legal_section("Third-party components", None, Gtk.License.CUSTOM,
            "Uses audible (AGPLv3), Mutagen (GPLv2 or later), GTK/Libadwaita/PyGObject (LGPL), WebKitGTK/libsoup, FFmpeg, Pillow, HTTPX and SecretStorage. See THIRD_PARTY.md in the source distribution for attribution and license obligations.")
        dialog.present(self)


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()
