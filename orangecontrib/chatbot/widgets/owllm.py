"""
Orange3 LLM Widget
==================

Widget for Language Model configuration.

Features:
- Shows only installed local Ollama models in the main selector.
- Allows deleting installed local Ollama models.
- Allows searching online models from the Ollama public library page.
- Supports "Load more models" below the online results table.
- Opens model tags/versions in a floating details window.
- Allows downloading selected model/tag using local Ollama.
"""

import json
import re
import html as html_lib
import urllib.request
import urllib.error
import urllib.parse

from AnyQt.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QWidget,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QProgressBar,
    QDialog,
    QPushButton,
)
from AnyQt.QtCore import Qt, QThread, pyqtSignal

from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


OLLAMA_BASE_URL = "http://127.0.0.1:11434"

PROMPT_OVERHEAD = 400
AVG_CHUNK_TOKENS = 150

KNOWN_TAGS = [
    "embedding",
    "vision",
    "tools",
    "thinking",
    "cloud",
    "code",
    "audio",
    "multimodal",
    "chat",
    "e2b",
]


def ollama_model_config(model_name):
    return {
        "type": "ollama",
        "model": model_name,
        "context_limit": 4096,
    }


def clean_html_text(text):
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate_text(text, limit=260):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def extract_first(pattern, text, default=""):
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return default
    return match.group(1).strip()


class OllamaPullWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            payload = json.dumps(
                {
                    "name": self.model_name,
                    "stream": True,
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/pull",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            success_seen = False

            with urllib.request.urlopen(request) as response:
                last_message = ""

                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()

                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except Exception:
                        self.progress.emit(line, -1)
                        continue

                    if "error" in data:
                        self.error.emit(data["error"])
                        return

                    status = data.get("status", "")
                    completed = data.get("completed")
                    total = data.get("total")

                    percent = -1

                    if status.lower() == "success":
                        success_seen = True
                        percent = 100

                    if completed is not None and total:
                        percent = int((completed / total) * 100)
                        message = f"{status} - {percent}%"
                    else:
                        message = status or str(data)

                    if message and message != last_message:
                        self.progress.emit(message, percent)
                        last_message = message

            if not success_seen:
                self.error.emit(
                    f"Download did not finish successfully. "
                    f"Check if the model name exists: {self.model_name}"
                )
                return

            self.finished.emit(self.model_name)

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="ignore")
                data = json.loads(body)
                message = data.get("error", body)
            except Exception:
                message = str(exc)

            self.error.emit(
                "Download failed. The model name may be invalid or unavailable. "
                f"Details: {message}"
            )

        except urllib.error.URLError as exc:
            self.error.emit(
                "Could not connect to Ollama. Make sure Ollama is running. "
                f"Details: {exc}"
            )

        except Exception as exc:
            self.error.emit(f"Unexpected download error: {exc}")


class OllamaDeleteWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model_name):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            payload = json.dumps(
                {
                    "model": self.model_name,
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/delete",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )

            with urllib.request.urlopen(request) as response:
                response.read()

            self.finished.emit(self.model_name)

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="ignore")
                data = json.loads(body)
                message = data.get("error", body)
            except Exception:
                message = str(exc)

            self.error.emit(f"Could not delete model. Details: {message}")

        except urllib.error.URLError as exc:
            self.error.emit(
                "Could not connect to Ollama. Make sure Ollama is running. "
                f"Details: {exc}"
            )

        except Exception as exc:
            self.error.emit(f"Unexpected delete error: {exc}")


class OllamaOnlineSearchWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query, filters, page, seen_models):
        super().__init__()
        self.query = (query or "").strip()
        self.filters = filters or {}
        self.page = max(1, int(page or 1))
        self.seen_models = set(seen_models or [])

    def run(self):
        try:
            encoded_query = urllib.parse.quote_plus(self.query)

            urls = self._build_candidate_urls(encoded_query, self.page)
            found = []

            for url in urls:
                page_html = self._download_page(url)
                rows = self._parse_search_page(page_html)

                for row in rows:
                    model_name = row.get("model", "")

                    if not model_name:
                        continue

                    if model_name in self.seen_models:
                        continue

                    if not self._passes_filters(row):
                        continue

                    self.seen_models.add(model_name)
                    found.append(row)

                if found:
                    break

            if not found:
                self.error.emit("No more unique online models found.")
                return

            self.finished.emit(found[:40])

        except Exception as exc:
            self.error.emit(str(exc))

    def _build_candidate_urls(self, encoded_query, page):
        urls = []
        domains = ["https://ollama.com", "https://www.ollama.com"]

        for domain in domains:
            if encoded_query:
                urls.extend(
                    [
                        f"{domain}/search?q={encoded_query}&page={page}",
                        f"{domain}/search?q={encoded_query}&p={page}",
                        f"{domain}/search?q={encoded_query}&offset={(page - 1) * 20}",
                        f"{domain}/search?q={encoded_query}",
                    ]
                )
            else:
                urls.extend(
                    [
                        f"{domain}/search?page={page}",
                        f"{domain}/search?p={page}",
                        f"{domain}/search?offset={(page - 1) * 20}",
                        f"{domain}/search",
                        f"{domain}/library?page={page}",
                        f"{domain}/library?p={page}",
                        f"{domain}/library",
                    ]
                )

        return urls

    def _download_page(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _parse_search_page(self, page_html):
        link_matches = list(
            re.finditer(r'href=["\'](/library/[^"\']+)["\']', page_html)
        )

        rows = []

        for index, match in enumerate(link_matches):
            link = match.group(1)
            model_name = self._model_from_link(link)

            if not model_name:
                continue

            anchor_start = page_html.rfind("<a", 0, match.start())
            if anchor_start < 0:
                anchor_start = match.start()

            if index + 1 < len(link_matches):
                next_anchor = page_html.rfind("<a", 0, link_matches[index + 1].start())
                block_end = (
                    next_anchor
                    if next_anchor > anchor_start
                    else link_matches[index + 1].start()
                )
            else:
                block_end = anchor_start + 3500

            block = page_html[anchor_start:block_end]
            info = self._extract_model_info(model_name, block)

            if not any(row["model"] == info["model"] for row in rows):
                rows.append(info)

        return rows

    def _model_from_link(self, link):
        path = link.replace("/library/", "", 1)
        path = path.split("?")[0].split("#")[0].strip("/")
        path = urllib.parse.unquote(path)
        path = html_lib.unescape(path)

        if path.endswith("/tags"):
            path = path[:-5].strip("/")

        if not path:
            return None

        if path in ("search", "library"):
            return None

        if path.count("/") > 1:
            return None

        return path

    def _extract_model_info(self, model_name, block):
        plain = clean_html_text(block)
        lower = plain.lower()

        tags = []

        for tag in KNOWN_TAGS:
            if re.search(rf"\b{re.escape(tag)}\b", lower):
                tags.append(tag)

        downloads = extract_first(
            r"([\d.,]+\s*[KMB]?)\s+(?:Pulls|Downloads)",
            plain,
            "",
        )

        tags_count = extract_first(
            r"(\d+)\s+Tags?",
            plain,
            "",
        )

        updated = extract_first(
            r"Updated\s+((?:\d+\s+\w+\s+ago)|(?:today)|(?:yesterday)|(?:\d+\s+\w+)|(?:[A-Za-z]+\s+\d{1,2},?\s+\d{4}))",
            plain,
            "",
        )

        description = plain

        pos = description.lower().find(model_name.lower())
        if pos >= 0:
            description = description[pos + len(model_name):].strip()

        description = re.split(
            r"\b[\d.,]+\s*[KMB]?\s+(?:Pulls|Downloads)\b|\b\d+\s+Tags?\b|\bUpdated\b",
            description,
            maxsplit=1,
            flags=re.I,
        )[0].strip()

        for tag in tags:
            description = re.sub(
                rf"\b{re.escape(tag)}\b",
                " ",
                description,
                flags=re.I,
            )

        description = re.sub(r"\s+", " ", description)
        description = description.strip(" -|•:,.\"'")

        return {
            "model": model_name,
            "tags": tags,
            "downloads": downloads,
            "tags_count": tags_count,
            "updated": updated,
            "description": truncate_text(description, 260),
        }

    def _passes_filters(self, info):
        active_filters = [
            name for name, enabled in self.filters.items() if enabled
        ]

        if not active_filters:
            return True

        text = (
            info.get("model", "")
            + " "
            + info.get("description", "")
            + " "
            + " ".join(info.get("tags", []))
        ).lower()

        return any(filter_name in text for filter_name in active_filters)


class OllamaModelTagsWorker(QThread):
    finished = pyqtSignal(str, list)
    error = pyqtSignal(str)

    def __init__(self, model_name):
        super().__init__()
        self.model_name = (model_name or "").strip()

    def run(self):
        try:
            if not self.model_name:
                self.error.emit("No model selected.")
                return

            base_model = self.model_name.split(":")[0]
            encoded_model = urllib.parse.quote(base_model, safe="/")

            urls = [
                f"https://ollama.com/library/{encoded_model}/tags",
                f"https://www.ollama.com/library/{encoded_model}/tags",
            ]

            tag_rows = []

            for url in urls:
                page = self._download_page(url)
                tag_rows = self._parse_tags_page(page, base_model)

                if tag_rows:
                    break

            if not tag_rows:
                self.error.emit(
                    f"No tags found online for {base_model}. "
                    "The model page may have changed."
                )
                return

            self.finished.emit(base_model, tag_rows[:100])

        except Exception as exc:
            self.error.emit(str(exc))

    def _download_page(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _parse_tags_page(self, page_html, base_model):
        candidates = []

        patterns = [
            r"ollama\s+(?:run|pull)\s+([A-Za-z0-9._/\-]+:[A-Za-z0-9._\-]+)",
            r'href=["\']/library/([^"\']+:[^"\']+)["\']',
            rf"\b({re.escape(base_model)}:[A-Za-z0-9._\-]+)\b",
        ]

        for pattern in patterns:
            for raw in re.findall(pattern, page_html):
                tag_name = raw.split("?")[0].split("#")[0].strip("/")
                tag_name = urllib.parse.unquote(tag_name)
                tag_name = html_lib.unescape(tag_name)

                if tag_name.startswith(base_model + ":"):
                    if tag_name not in candidates:
                        candidates.append(tag_name)

        if base_model not in candidates:
            candidates.insert(0, base_model)

        rows = []

        for tag_name in candidates:
            block = self._block_around(page_html, tag_name)
            plain = clean_html_text(block)

            size = extract_first(
                r"(\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB))",
                plain,
                "",
            )

            context = extract_first(
                r"(\d+(?:K|k))\s*(?:context)?",
                plain,
                "",
            )

            input_type = ""

            if re.search(r"\bVision\b", plain, flags=re.I):
                input_type = "Vision"
            elif re.search(r"\bText\b", plain, flags=re.I):
                input_type = "Text"

            rows.append(
                {
                    "name": tag_name,
                    "size": size,
                    "context": context,
                    "input": input_type,
                }
            )

        unique_rows = []
        seen = set()

        for row in rows:
            if row["name"] in seen:
                continue

            seen.add(row["name"])
            unique_rows.append(row)

        return unique_rows

    def _block_around(self, page_html, text, radius=1200):
        pos = page_html.find(text)

        if pos < 0:
            return ""

        start = max(0, pos - radius)
        end = min(len(page_html), pos + radius)

        return page_html[start:end]


class ModelDetailsDialog(QDialog):
    def __init__(self, parent, model_name, tag_rows, is_installed_callback):
        super().__init__(parent)

        self.model_name = model_name
        self.tag_rows = tag_rows or []
        self.is_installed_callback = is_installed_callback
        self.selected_model_name = None

        self.setWindowTitle(f"Model details - {model_name}")
        self.resize(850, 460)

        layout = QVBoxLayout(self)

        title = QLabel(f"Tags / Versions for: {model_name}")
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Status", "Size", "Context", "Input"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.table)

        button_row = QHBoxLayout()

        self.download_button = QPushButton("Download selected tag/version")
        self.close_button = QPushButton("Close")

        button_row.addWidget(self.download_button)
        button_row.addWidget(self.close_button)

        layout.addLayout(button_row)

        self.download_button.clicked.connect(self.accept_download)
        self.close_button.clicked.connect(self.reject)

        self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(len(self.tag_rows))

        for row_idx, row in enumerate(self.tag_rows):
            name = row.get("name", "")
            size = row.get("size", "")
            context = row.get("context", "")
            input_type = row.get("input", "")
            status = "installed" if self.is_installed_callback(name) else "not installed"

            values = [name, status, size, context, input_type]

            for col_idx, value in enumerate(values):
                self.table.setItem(
                    row_idx,
                    col_idx,
                    QTableWidgetItem(str(value)),
                )

        self.table.resizeColumnsToContents()

        if self.tag_rows:
            self.table.selectRow(0)

    def accept_download(self):
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            return

        row_idx = selected_rows[0].row()

        if row_idx < 0 or row_idx >= len(self.tag_rows):
            return

        self.selected_model_name = self.tag_rows[row_idx].get("name")
        self.accept()


class OWLLM(widget.OWWidget):
    name = "LLM"
    description = "Language Model configuration for chat"
    icon = "icons/llm.svg"
    priority = 90
    keywords = ["llm", "language model", "ai", "ollama"]

    want_main_area = True
    resizing_enabled = True

    selected_llm = settings.Setting(0)
    selected_model_name = settings.Setting("")

    online_search_query = settings.Setting("")
    filter_embedding = settings.Setting(False)
    filter_vision = settings.Setting(False)
    filter_tools = settings.Setting(False)
    filter_thinking = settings.Setting(False)
    filter_cloud = settings.Setting(False)

    temperature_pct = settings.Setting(4)
    temperature = settings.Setting(0.4)
    max_tokens = settings.Setting(2048)
    streaming = settings.Setting(True)
    show_advanced = settings.Setting(False)

    class Inputs:
        retriever = Input("Retriever", object)
        prompt_config = Input("Prompt Config", dict)

    class Outputs:
        llm_config = Output("LLM Config", dict)

    def __init__(self):
        super().__init__()

        self.retriever = None
        self.prompt_config = None
        self.llm_config = None
        self.max_tokens_spin = None
        self.adv_inner = None

        self.pull_worker = None
        self.delete_worker = None
        self.online_search_worker = None
        self.tags_worker = None

        self.installed_ollama_models = []
        self.online_model_rows = []
        self.online_search_page = 1

        self.model_options = {}
        self.model_names = []

        self._rebuild_model_options(update_combo=False)

        self._setup_gui()

        self.refresh_installed_models(silent=True)

        self._sync_temperature_from_slider()
        self._update_token_cap()
        self._update_config()

    def _setup_gui(self):
        top_row = QWidget(self.controlArea)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(6)
        self.controlArea.layout().addWidget(top_row)

        model_box = gui.widgetBox(top_row, "Model Selection")
        top_row_layout.addWidget(model_box, 1)

        self.model_combo = gui.comboBox(
            model_box,
            self,
            "selected_llm",
            label="Model:",
            items=self.model_names,
            callback=self._on_model_changed,
        )

        self.model_info_label = gui.label(model_box, self, "")
        self.model_info_label.setWordWrap(True)

        gui.button(
            model_box,
            self,
            "Refresh installed models",
            callback=self.refresh_installed_models,
        )

        self._update_model_info()

        tone_box = gui.widgetBox(top_row, "Response Style")
        top_row_layout.addWidget(tone_box, 1)
        self.tone_box = tone_box

        gui.hSlider(
            tone_box,
            self,
            "temperature_pct",
            minValue=1,
            maxValue=7,
            step=1,
            label="Tone:",
            createLabel=False,
            ticks=True,
            callback=self._on_temperature_slider_changed,
        )

        lbl_widget = QWidget()
        lbl_layout = QHBoxLayout(lbl_widget)
        lbl_layout.setContentsMargins(8, 0, 8, 2)

        for txt, align in [
            ("Precise", Qt.AlignLeft),
            ("Balanced", Qt.AlignCenter),
            ("Creative", Qt.AlignRight),
        ]:
            lbl = QLabel(txt)
            lbl.setAlignment(align)
            lbl_layout.addWidget(lbl)

        tone_box.layout().addWidget(lbl_widget)

        manager_box = gui.widgetBox(self.controlArea, "Ollama Local Models")

        self.installed_models_label = gui.label(
            manager_box,
            self,
            "Installed Ollama models: checking...",
        )
        self.installed_models_label.setWordWrap(True)

        self.delete_selected_button = gui.button(
            manager_box,
            self,
            "Delete selected installed model",
            callback=self.delete_selected_model,
        )

        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setMinimum(0)
        self.download_progress_bar.setMaximum(100)
        self.download_progress_bar.setValue(0)
        manager_box.layout().addWidget(self.download_progress_bar)

        self.download_status_label = gui.label(
            manager_box,
            self,
            "Ready",
        )
        self.download_status_label.setWordWrap(True)

        online_controls_box = gui.widgetBox(self.controlArea, "Online Model Search")

        gui.lineEdit(
            online_controls_box,
            self,
            "online_search_query",
            label="Search online:",
        )

        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        online_controls_box.layout().addWidget(filter_row)

        gui.checkBox(filter_row, self, "filter_embedding", label="Embedding")
        gui.checkBox(filter_row, self, "filter_vision", label="Vision")
        gui.checkBox(filter_row, self, "filter_tools", label="Tools")
        gui.checkBox(filter_row, self, "filter_thinking", label="Thinking")
        gui.checkBox(filter_row, self, "filter_cloud", label="Cloud")

        self.search_online_button = gui.button(
            online_controls_box,
            self,
            "Search online models",
            callback=self.search_online_models,
        )

        self.open_details_button = gui.button(
            online_controls_box,
            self,
            "Open selected model details",
            callback=self.open_selected_model_details,
        )
        self.open_details_button.setEnabled(False)

        self.online_status_label = gui.label(
            online_controls_box,
            self,
            "Search online models from the Ollama public library.",
        )
        self.online_status_label.setWordWrap(True)

        rag_box = gui.widgetBox(self.controlArea, "RAG Status")
        self.rag_status_label = gui.label(
            rag_box,
            self,
            "Waiting for retriever...",
        )

        prompt_box = gui.widgetBox(self.controlArea, "Dataset Prompt Status")
        self.prompt_status_label = gui.label(
            prompt_box,
            self,
            "Waiting for prompt config...",
        )

        info_box = gui.widgetBox(self.controlArea, "Info")
        self.info_label = gui.label(
            info_box,
            self,
            "This widget configures the LLM\n"
            "for use in the workflow.\n\n"
            "Use the online search table in\n"
            "the center area to find models.\n\n"
            "Double-click a model to open\n"
            "its tags/versions."
        )

        gui.checkBox(
            self.controlArea,
            self,
            "show_advanced",
            label="Show advanced settings",
            callback=self._on_advanced_visibility_changed,
        )

        self.adv_inner = gui.widgetBox(self.controlArea, "Advanced Settings")

        gui.doubleSpin(
            self.adv_inner,
            self,
            "temperature",
            minv=0.0,
            maxv=2.0,
            step=0.1,
            label="Manual temperature:",
            callback=self._on_manual_temperature_changed,
        )

        self.max_tokens_spin = gui.spin(
            self.adv_inner,
            self,
            "max_tokens",
            minv=800,
            maxv=32768,
            step=256,
            label="Max tokens:",
            callback=self._update_config,
        )

        self.token_info_label = gui.label(self.adv_inner, self, "")
        self.token_info_label.setWordWrap(True)
        self.token_info_label.setStyleSheet("color: gray; font-size: 10px;")

        gui.checkBox(
            self.adv_inner,
            self,
            "streaming",
            label="Enable streaming",
            callback=self._update_config,
        )

        self.adv_inner.setVisible(self.show_advanced)
        self.tone_box.setEnabled(not self.show_advanced)

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        search_title = QLabel("Online Search Results")
        main_layout.addWidget(search_title)

        self.online_results_table = QTableWidget()
        self.online_results_table.setColumnCount(7)
        self.online_results_table.setHorizontalHeaderLabels(
            [
                "Model",
                "Status",
                "Tags",
                "Downloads",
                "Tags Count",
                "Updated",
                "Description",
            ]
        )
        self.online_results_table.setRowCount(0)
        self.online_results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.online_results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.online_results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.online_results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.online_results_table.horizontalHeader().setStretchLastSection(True)
        self.online_results_table.itemSelectionChanged.connect(
            self.on_online_selection_changed
        )
        self.online_results_table.doubleClicked.connect(
            self.open_selected_model_details
        )

        main_layout.addWidget(self.online_results_table)

        self.load_more_button = QPushButton("Load more models")
        self.load_more_button.clicked.connect(self.load_more_online_models)
        self.load_more_button.setEnabled(False)
        main_layout.addWidget(self.load_more_button)

        self.mainArea.layout().addWidget(main_widget)

    # ------------------------------------------------------------------
    # Local Ollama models
    # ------------------------------------------------------------------

    def _make_model_options(self):
        options = {}

        for model_name in self.installed_ollama_models:
            options[model_name] = ollama_model_config(model_name)

        return options

    def _rebuild_model_options(self, update_combo=True):
        current_name = self.selected_model_name

        self.model_options = self._make_model_options()
        self.model_names = list(self.model_options.keys())

        if not self.model_names:
            self.model_names = ["No local Ollama models installed"]
            self.model_options["No local Ollama models installed"] = {
                "type": "none",
                "model": "",
                "context_limit": 4096,
            }

        if current_name not in self.model_names:
            current_name = self.model_names[0]

        self.selected_model_name = current_name
        self.selected_llm = self.model_names.index(current_name)

        if update_combo and hasattr(self, "model_combo"):
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItems(self.model_names)
            self.model_combo.setCurrentIndex(self.selected_llm)
            self.model_combo.blockSignals(False)

    def refresh_installed_models(self, silent=False):
        try:
            request = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/tags",
                method="GET",
            )

            with urllib.request.urlopen(request, timeout=5) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)

            models = data.get("models", [])
            names = []

            for model in models:
                name = model.get("name") or model.get("model")
                if name:
                    names.append(name)

            self.installed_ollama_models = sorted(set(names))
            self._rebuild_model_options(update_combo=True)

            if self.installed_ollama_models:
                preview = ", ".join(self.installed_ollama_models[:8])
                if len(self.installed_ollama_models) > 8:
                    preview += ", ..."

                self.installed_models_label.setText(
                    f"Installed Ollama models ({len(self.installed_ollama_models)}): {preview}"
                )
            else:
                self.installed_models_label.setText(
                    "Installed Ollama models: none found"
                )

            if not silent:
                self.download_status_label.setText("Installed model list updated.")

            self._refresh_online_table()
            self._update_model_info()
            self._update_token_cap()
            self._update_config()

        except Exception as exc:
            self.installed_models_label.setText(
                "Installed Ollama models: could not connect to Ollama."
            )

            if not silent:
                self.download_status_label.setText(
                    f"Could not refresh installed models: {exc}"
                )

    def _find_installed_model_name(self, model_name):
        requested = (model_name or "").strip()

        if not requested:
            return None

        if requested in self.installed_ollama_models:
            return requested

        if ":" not in requested:
            latest_name = requested + ":latest"

            if latest_name in self.installed_ollama_models:
                return latest_name

            for installed_name in self.installed_ollama_models:
                installed_base = installed_name.split(":")[0]

                if installed_base == requested:
                    return installed_name

        return None

    def _is_model_installed(self, model_name):
        return self._find_installed_model_name(model_name) is not None

    # ------------------------------------------------------------------
    # Download / delete
    # ------------------------------------------------------------------

    def _set_download_controls_enabled(self, enabled):
        self.delete_selected_button.setEnabled(enabled)

        if hasattr(self, "search_online_button"):
            self.search_online_button.setEnabled(enabled)

        if hasattr(self, "load_more_button"):
            self.load_more_button.setEnabled(enabled and bool(self.online_model_rows))

        if hasattr(self, "open_details_button"):
            self.open_details_button.setEnabled(
                enabled and self._selected_online_model_name() is not None
            )

    def _start_model_download(self, model_name):
        if self.pull_worker is not None and self.pull_worker.isRunning():
            self.download_status_label.setText(
                "Another model is already downloading. Please wait."
            )
            return

        self._set_download_controls_enabled(False)

        self.download_progress_bar.setValue(0)
        self.download_status_label.setText(f"Starting download: {model_name}")

        self.pull_worker = OllamaPullWorker(model_name)
        self.pull_worker.progress.connect(self.on_download_progress)
        self.pull_worker.finished.connect(self.on_download_finished)
        self.pull_worker.error.connect(self.on_download_error)
        self.pull_worker.start()

    def on_download_progress(self, message, percent):
        self.download_status_label.setText(message)

        if percent >= 0:
            self.download_progress_bar.setValue(max(0, min(100, percent)))

    def on_download_finished(self, model_name):
        self._set_download_controls_enabled(True)

        self.download_progress_bar.setValue(100)

        self.refresh_installed_models(silent=True)

        installed_name = self._find_installed_model_name(model_name)

        if installed_name is None:
            self.download_status_label.setText(
                f"Download failed: model not found or invalid model name: {model_name}"
            )
            return

        self.download_status_label.setText(f"Download complete: {installed_name}")

        self.selected_model_name = installed_name

        if installed_name in self.model_names:
            self.selected_llm = self.model_names.index(installed_name)
            self.model_combo.setCurrentIndex(self.selected_llm)

        self._on_model_changed()

    def on_download_error(self, message):
        self._set_download_controls_enabled(True)

        self.download_progress_bar.setValue(0)
        self.download_status_label.setText(f"Download error: {message}")

    def delete_selected_model(self):
        model_name = self._selected_model_name()
        model_config = self._selected_model_config()

        if model_config.get("type") != "ollama":
            self.download_status_label.setText(
                "Only installed local Ollama models can be deleted."
            )
            return

        if model_name not in self.installed_ollama_models:
            self.download_status_label.setText(
                f"Model is not installed locally: {model_name}"
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete Ollama model",
            f"Are you sure you want to delete this model?\n\n{model_name}\n\n"
            "This removes the model from your local Ollama storage.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        if self.pull_worker is not None and self.pull_worker.isRunning():
            self.download_status_label.setText(
                "A model is currently downloading. Wait before deleting."
            )
            return

        if self.delete_worker is not None and self.delete_worker.isRunning():
            self.download_status_label.setText(
                "A model is already being deleted. Please wait."
            )
            return

        self._set_download_controls_enabled(False)
        self.download_status_label.setText(f"Deleting model: {model_name}")

        self.delete_worker = OllamaDeleteWorker(model_name)
        self.delete_worker.finished.connect(self.on_delete_finished)
        self.delete_worker.error.connect(self.on_delete_error)
        self.delete_worker.start()

    def on_delete_finished(self, model_name):
        self._set_download_controls_enabled(True)

        self.download_status_label.setText(f"Deleted model: {model_name}")

        self.selected_model_name = ""
        self.refresh_installed_models(silent=True)
        self._on_model_changed()

    def on_delete_error(self, message):
        self._set_download_controls_enabled(True)

        self.download_status_label.setText(f"Delete error: {message}")

    # ------------------------------------------------------------------
    # Online search
    # ------------------------------------------------------------------

    def _current_filters(self):
        return {
            "embedding": self.filter_embedding,
            "vision": self.filter_vision,
            "tools": self.filter_tools,
            "thinking": self.filter_thinking,
            "cloud": self.filter_cloud,
        }

    def search_online_models(self):
        self.online_search_page = 1
        self.online_model_rows = []
        self._refresh_online_table()
        self._run_online_search(page=1)

    def load_more_online_models(self):
        self.online_search_page += 1
        self._run_online_search(page=self.online_search_page)

    def _run_online_search(self, page):
        query = (self.online_search_query or "").strip()

        if self.online_search_worker is not None and self.online_search_worker.isRunning():
            self.online_status_label.setText("Search already running. Please wait.")
            return

        seen_models = [row.get("model") for row in self.online_model_rows]

        self.search_online_button.setEnabled(False)
        self.load_more_button.setEnabled(False)
        self.open_details_button.setEnabled(False)

        if query:
            self.online_status_label.setText(
                f"Searching online models for: {query} | load page {page}"
            )
        else:
            self.online_status_label.setText(
                f"Searching online models | load page {page}"
            )

        self.online_search_worker = OllamaOnlineSearchWorker(
            query=query,
            filters=self._current_filters(),
            page=page,
            seen_models=seen_models,
        )
        self.online_search_worker.finished.connect(self.on_online_search_finished)
        self.online_search_worker.error.connect(self.on_online_search_error)
        self.online_search_worker.start()

    def on_online_search_finished(self, rows):
        self.search_online_button.setEnabled(True)

        self.online_model_rows.extend(rows)

        self._refresh_online_table()

        self.load_more_button.setEnabled(True)
        self.open_details_button.setEnabled(
            self._selected_online_model_name() is not None
        )

        self.online_status_label.setText(
            f"Showing {len(self.online_model_rows)} online model(s). "
            "Use Load more models to try loading more."
        )

    def on_online_search_error(self, message):
        self.search_online_button.setEnabled(True)
        self.load_more_button.setEnabled(bool(self.online_model_rows))
        self.open_details_button.setEnabled(
            self._selected_online_model_name() is not None
        )

        self.online_status_label.setText(
            f"Online search: {message}. "
            "The site may have no more visible results for this search."
        )

    def _refresh_online_table(self):
        if not hasattr(self, "online_results_table"):
            return

        self.online_results_table.setRowCount(len(self.online_model_rows))

        for row_idx, row in enumerate(self.online_model_rows):
            model_name = row.get("model", "")
            tags = ", ".join(row.get("tags", []))
            downloads = row.get("downloads", "")
            tags_count = row.get("tags_count", "")
            updated = row.get("updated", "")
            description = row.get("description", "")
            status = "installed" if self._is_model_installed(model_name) else "not installed"

            values = [
                model_name,
                status,
                tags,
                downloads,
                tags_count,
                updated,
                description,
            ]

            for col_idx, value in enumerate(values):
                self.online_results_table.setItem(
                    row_idx,
                    col_idx,
                    QTableWidgetItem(str(value)),
                )

        self.online_results_table.resizeColumnsToContents()

        if self.online_model_rows and not self.online_results_table.selectedItems():
            self.online_results_table.selectRow(0)

    def on_online_selection_changed(self):
        selected_model = self._selected_online_model_name()
        self.open_details_button.setEnabled(selected_model is not None)

    def _selected_online_model_name(self):
        if not hasattr(self, "online_results_table"):
            return None

        selected_rows = self.online_results_table.selectionModel().selectedRows()

        if not selected_rows:
            return None

        row_idx = selected_rows[0].row()

        if row_idx < 0 or row_idx >= len(self.online_model_rows):
            return None

        return self.online_model_rows[row_idx].get("model")

    def open_selected_model_details(self):
        model_name = self._selected_online_model_name()

        if not model_name:
            self.online_status_label.setText("Select an online model first.")
            return

        if self.tags_worker is not None and self.tags_worker.isRunning():
            self.online_status_label.setText("Tag search already running. Please wait.")
            return

        self.open_details_button.setEnabled(False)
        self.online_status_label.setText(f"Fetching tags/versions for {model_name}...")

        self.tags_worker = OllamaModelTagsWorker(model_name)
        self.tags_worker.finished.connect(self.on_tags_finished)
        self.tags_worker.error.connect(self.on_tags_error)
        self.tags_worker.start()

    def on_tags_finished(self, base_model, tag_rows):
        self.open_details_button.setEnabled(True)

        self.online_status_label.setText(
            f"Found {len(tag_rows)} tag/version(s) for {base_model}."
        )

        dialog = ModelDetailsDialog(
            parent=self,
            model_name=base_model,
            tag_rows=tag_rows,
            is_installed_callback=self._is_model_installed,
        )

        result = dialog.exec_()

        if result == QDialog.Accepted and dialog.selected_model_name:
            self._start_model_download(dialog.selected_model_name)

    def on_tags_error(self, message):
        self.open_details_button.setEnabled(True)

        self.online_status_label.setText(
            f"Could not fetch tags: {message}"
        )

    # ------------------------------------------------------------------
    # Model config
    # ------------------------------------------------------------------

    def _selected_model_name(self):
        if not self.model_names:
            self._rebuild_model_options(update_combo=False)

        self.selected_llm = max(0, min(self.selected_llm, len(self.model_names) - 1))
        return self.model_names[self.selected_llm]

    def _selected_model_config(self):
        model_name = self._selected_model_name()
        return self.model_options[model_name]

    def _update_model_info(self):
        model_name = self._selected_model_name()
        config = self._selected_model_config()

        if config["type"] == "ollama":
            self.model_info_label.setText("Type: ollama | Status: installed")
        elif config["type"] == "none":
            self.model_info_label.setText("No installed local model selected")
        else:
            self.model_info_label.setText(f"Type: {config['type']}")

    def _on_model_changed(self):
        if self.model_names:
            self.selected_llm = max(
                0,
                min(self.selected_llm, len(self.model_names) - 1),
            )

            self.selected_model_name = self.model_names[self.selected_llm]

        self._update_model_info()
        self._update_token_cap()
        self._update_config()

    def _sync_temperature_from_slider(self):
        self.temperature = round(self.temperature_pct * 0.1, 1)

    def _on_temperature_slider_changed(self):
        self._sync_temperature_from_slider()
        self._update_config()

    def _on_manual_temperature_changed(self):
        self.temperature = min(2.0, max(0.0, round(self.temperature, 1)))
        self.temperature_pct = min(7, max(1, int(round(self.temperature * 10))))
        self._update_config()

    def _on_advanced_visibility_changed(self):
        if self.adv_inner is not None:
            self.adv_inner.setVisible(self.show_advanced)

        if hasattr(self, "tone_box"):
            self.tone_box.setEnabled(not self.show_advanced)

        self._update_model_info()
        self._update_token_cap()
        self._update_config()

    def _update_token_cap(self):
        config = self._selected_model_config()
        context_limit = config.get("context_limit", 4096)

        top_k = 5

        if self.retriever is not None and hasattr(self.retriever, "search_kwargs"):
            top_k = self.retriever.search_kwargs.get("k", 5)

        retrieved_tokens = top_k * AVG_CHUNK_TOKENS
        available_context = max(1, context_limit - PROMPT_OVERHEAD - retrieved_tokens)
        suggested_max_tokens = min(800, available_context)

        if self.max_tokens_spin is not None:
            self.max_tokens_spin.setMinimum(1)
            self.max_tokens_spin.setMaximum(available_context)

        if not self.show_advanced:
            self.max_tokens = suggested_max_tokens
        elif self.max_tokens > available_context or self.max_tokens < 1:
            self.max_tokens = suggested_max_tokens

        if hasattr(self, "token_info_label"):
            if self.show_advanced:
                self.token_info_label.setText(
                    f"{context_limit:,} - {PROMPT_OVERHEAD} prompt overhead "
                    f"- {retrieved_tokens} retrieved ({top_k}x{AVG_CHUNK_TOKENS}) "
                    f"= {available_context:,} available "
                    f"(suggested max_tokens: {suggested_max_tokens:,})"
                )
            else:
                self.token_info_label.setText("")

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    @Inputs.retriever
    def set_retriever(self, retriever):
        self.retriever = retriever

        if retriever is None:
            self.rag_status_label.setText("⚠ Waiting for retriever...")
            self.info.set_input_summary(self.info.NoInput)
        else:
            self.rag_status_label.setText("✓ Retriever connected")
            self.info.set_input_summary("Retriever connected")

        self._update_token_cap()
        self._update_config()

    @Inputs.prompt_config
    def set_prompt_config(self, prompt_config):
        self.prompt_config = prompt_config

        if prompt_config is None:
            self.prompt_status_label.setText("⚠ Waiting for prompt config...")
        else:
            total = prompt_config.get("total_examples", 0)
            layer_name = prompt_config.get("layer_name", "Prompt Layer")

            self.prompt_status_label.setText(
                f"✓ Prompt Config connected: {layer_name} ({total} examples)"
            )

        self._update_token_cap()
        self._update_config()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _update_config(self):
        model_name = self._selected_model_name()
        model_config = self._selected_model_config()

        if model_config["type"] == "none":
            self.Outputs.llm_config.send(None)
            self.info.set_output_summary(self.info.NoOutput)
            return

        layer_name = None

        if self.prompt_config is not None:
            layer_name = self.prompt_config.get("layer_name", "Prompt Layer")

        if self.retriever is None and self.prompt_config is None:
            self.Outputs.llm_config.send(None)
            self.info.set_output_summary(self.info.NoOutput)
            return

        effective_temperature = (
            self.temperature
            if self.show_advanced
            else round(self.temperature_pct * 0.1, 1)
        )

        self.llm_config = {
            "model_name": model_name,
            "model_type": model_config["type"],
            "model": model_config["model"],
            "temperature": effective_temperature,
            "max_tokens": self.max_tokens,
            "streaming": self.streaming,

            "retriever": self.retriever,
            "rag_enabled": self.retriever is not None,

            "prompt_config": self.prompt_config,
            "dataset_prompt_enabled": self.prompt_config is not None,
            "layer_name": layer_name,
        }

        self.Outputs.llm_config.send(self.llm_config)

        if self.retriever is not None and self.prompt_config is not None:
            summary = f"{model_name} with RAG + Dataset Prompt: {layer_name}"
        elif self.retriever is not None:
            summary = f"{model_name} with RAG"
        elif self.prompt_config is not None:
            summary = f"{model_name} with Dataset Prompt: {layer_name}"
        else:
            summary = model_name

        self.info.set_output_summary(summary)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(OWLLM).run()