"""
Orange3 LLM Results Widget
==========================

Widget for running multiple LLM configurations over dataset prompt examples,
showing all layer responses, and calculating evaluation metrics.

Views:
- Summary: average metrics by layer/model.
- Question Details: target, responses and metrics for one selected question.
- Raw Results: full table for export/debugging.
"""

import json
import math
import re
import time
import unicodedata
import urllib.request
from collections import Counter

import numpy as np

from AnyQt.QtCore import QThread, pyqtSignal
from AnyQt.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QLabel,
    QDialog,
    QTextEdit,
    QDialogButtonBox,
    QHeaderView,
    QAbstractItemView,
    QTabWidget,
)

from Orange.data import Table, Domain, StringVariable
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


OLLAMA_BASE_URL = "http://127.0.0.1:11434"


# ----------------------------------------------------------------------
# Text metrics helpers
# ----------------------------------------------------------------------

def normalize_text(text):
    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text):
    normalized = normalize_text(text)

    if not normalized:
        return []

    return normalized.split()


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def format_score(value):
    if isinstance(value, str):
        return value

    try:
        return f"{float(value):.4f}"
    except Exception:
        return "ERR"


def ngrams(tokens, n):
    if len(tokens) < n:
        return []

    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def lcs_length(a, b):
    if not a or not b:
        return 0

    a = a[:600]
    b = b[:600]

    previous = [0] * (len(b) + 1)

    for token_a in a:
        current = [0]

        for j, token_b in enumerate(b, 1):
            if token_a == token_b:
                current.append(previous[j - 1] + 1)
            else:
                current.append(max(previous[j], current[-1]))

        previous = current

    return previous[-1]


def f1_from_precision_recall(precision, recall):
    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def exact_match_score(target, response):
    return 1.0 if normalize_text(target) == normalize_text(response) else 0.0


def bleu_score(target, response, max_n=4):
    ref_tokens = tokenize(target)
    cand_tokens = tokenize(response)

    if not ref_tokens or not cand_tokens:
        return 0.0

    precisions = []

    for n in range(1, max_n + 1):
        ref_counts = Counter(ngrams(ref_tokens, n))
        cand_counts = Counter(ngrams(cand_tokens, n))

        total = sum(cand_counts.values())

        if total == 0:
            precisions.append(1.0 / (len(cand_tokens) + 1))
            continue

        overlap = 0

        for gram, count in cand_counts.items():
            overlap += min(count, ref_counts.get(gram, 0))

        precisions.append((overlap + 1) / (total + 1))

    geo_mean = math.exp(sum(math.log(p) for p in precisions) / max_n)

    ref_len = len(ref_tokens)
    cand_len = len(cand_tokens)

    if cand_len == 0:
        return 0.0

    brevity_penalty = 1.0 if cand_len > ref_len else math.exp(1 - ref_len / cand_len)

    return brevity_penalty * geo_mean


def rouge_scores(target, response):
    ref_tokens = tokenize(target)
    cand_tokens = tokenize(response)

    if not ref_tokens or not cand_tokens:
        return {
            "ROUGE-1": 0.0,
            "ROUGE-2": 0.0,
            "ROUGE-L": 0.0,
        }

    def rouge_n(n):
        ref_counts = Counter(ngrams(ref_tokens, n))
        cand_counts = Counter(ngrams(cand_tokens, n))

        if not ref_counts or not cand_counts:
            return 0.0

        overlap = 0

        for gram, count in cand_counts.items():
            overlap += min(count, ref_counts.get(gram, 0))

        precision = overlap / max(1, sum(cand_counts.values()))
        recall = overlap / max(1, sum(ref_counts.values()))

        return f1_from_precision_recall(precision, recall)

    lcs = lcs_length(ref_tokens, cand_tokens)

    rouge_l_precision = lcs / max(1, len(cand_tokens))
    rouge_l_recall = lcs / max(1, len(ref_tokens))

    return {
        "ROUGE-1": rouge_n(1),
        "ROUGE-2": rouge_n(2),
        "ROUGE-L": f1_from_precision_recall(rouge_l_precision, rouge_l_recall),
    }


def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0

    length = min(len(vec_a), len(vec_b))
    a = vec_a[:length]
    b = vec_b[:length]

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def parse_time_seconds(value):
    text = str(value or "").strip().lower().replace("s", "")

    try:
        return float(text)
    except Exception:
        return None


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------

class ResultsWorker(QThread):
    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(list, list, list)
    error = pyqtSignal(str)

    def __init__(self, llm_configs, metrics_config):
        super().__init__()

        self.llm_configs = llm_configs
        self.metrics_config = metrics_config or {}
        self.embedding_cache = {}

    def run(self):
        try:
            if not self.llm_configs:
                self.error.emit("No LLM Config received.")
                return

            valid_configs = []

            for config in self.llm_configs:
                prompt_config = config.get("prompt_config") or {}
                examples = prompt_config.get("examples", [])

                if examples:
                    valid_configs.append(config)

            if not valid_configs:
                self.error.emit("No prompt examples found in LLM Configs.")
                return

            base_prompt_config = valid_configs[0].get("prompt_config") or {}
            base_examples = base_prompt_config.get("examples", [])

            rows_by_index = {}

            for example in base_examples:
                row_index = str(example.get("row_index", len(rows_by_index)))

                rows_by_index[row_index] = {
                    "row_index": row_index,
                    "question": str(example.get("question", "")),
                    "target": str(example.get("expected_answer", "")),
                }

            layer_names = []

            for config_index, config in enumerate(valid_configs):
                prompt_config = config.get("prompt_config") or {}
                examples = prompt_config.get("examples", [])

                layer_name = config.get("layer_name") or prompt_config.get(
                    "layer_name", f"Layer {config_index + 1}"
                )

                model_name = config.get("model_name", "Unknown")
                rag_enabled = (
                    config.get("rag_enabled", False)
                    and config.get("retriever") is not None
                )

                display_layer_name = self._unique_layer_name(
                    layer_name=layer_name,
                    model_name=model_name,
                    rag_enabled=rag_enabled,
                    existing=layer_names,
                )

                layer_names.append(display_layer_name)

                total = len(examples)
                self.progress.emit(display_layer_name, 0, total, "Iniciando")

                llm = self._create_llm(config)

                for i, example in enumerate(examples):
                    row_index = str(example.get("row_index", i))
                    question = str(example.get("question", ""))
                    target = str(example.get("expected_answer", ""))

                    if row_index not in rows_by_index:
                        rows_by_index[row_index] = {
                            "row_index": row_index,
                            "question": question,
                            "target": target,
                        }

                    rag_context = ""

                    if rag_enabled:
                        self.progress.emit(
                            display_layer_name,
                            i,
                            total,
                            "Buscando contexto RAG",
                        )

                        rag_context = self._retrieve_context(
                            config.get("retriever"),
                            question,
                        )

                    final_prompt = self._build_prompt(
                        prompt_config=prompt_config,
                        example=example,
                        question=question,
                        rag_context=rag_context,
                    )

                    self.progress.emit(
                        display_layer_name,
                        i + 1,
                        total,
                        "Gerando resposta",
                    )

                    start_time = time.time()
                    raw_response = llm.invoke(final_prompt)
                    elapsed_time = time.time() - start_time

                    response = str(raw_response)

                    rows_by_index[row_index][display_layer_name] = response

                    if self.metrics_config.get("response_time", True):
                        rows_by_index[row_index][display_layer_name + " - time"] = (
                            f"{elapsed_time:.3f}s"
                        )

                    self.progress.emit(
                        display_layer_name,
                        i + 1,
                        total,
                        "Calculando métricas",
                    )

                    metric_values = self._compute_metrics(target, response)

                    for suffix, value in metric_values.items():
                        rows_by_index[row_index][display_layer_name + " - " + suffix] = value

                    status = "Concluído" if (i + 1) == total else "Rodando"
                    self.progress.emit(display_layer_name, i + 1, total, status)

            rows = list(rows_by_index.values())

            rows.sort(
                key=lambda row: (
                    0,
                    int(row["row_index"])
                )
                if str(row["row_index"]).isdigit()
                else (
                    1,
                    str(row["row_index"])
                )
            )

            self.finished.emit(rows, layer_names, self._metric_suffixes())

        except Exception as exc:
            self.error.emit(str(exc))

    def _metric_suffixes(self):
        suffixes = []

        if self.metrics_config.get("response_time", True):
            suffixes.append("time")

        if self.metrics_config.get("exact_match", True):
            suffixes.append("EM")

        if self.metrics_config.get("bleu", True):
            suffixes.append("BLEU")

        if self.metrics_config.get("rouge", True):
            suffixes.extend(["ROUGE-1", "ROUGE-2", "ROUGE-L"])

        if self.metrics_config.get("bert_score", False):
            suffixes.append("BERTScore-F1")

        if self.metrics_config.get("embedding_similarity", True):
            suffixes.append("Embedding Similarity")

        return suffixes

    def _compute_metrics(self, target, response):
        values = {}

        if self.metrics_config.get("exact_match", True):
            values["EM"] = format_score(exact_match_score(target, response))

        if self.metrics_config.get("bleu", True):
            values["BLEU"] = format_score(bleu_score(target, response))

        if self.metrics_config.get("rouge", True):
            for name, score in rouge_scores(target, response).items():
                values[name] = format_score(score)

        if self.metrics_config.get("bert_score", False):
            values["BERTScore-F1"] = self._bert_score(target, response)

        if self.metrics_config.get("embedding_similarity", True):
            values["Embedding Similarity"] = self._embedding_similarity(target, response)

        return values

    def _bert_score(self, target, response):
        if not str(target).strip() or not str(response).strip():
            return "0.0000"

        try:
            from bert_score import score as bert_score_fn

            _, _, f1 = bert_score_fn(
                [str(response)],
                [str(target)],
                lang=self.metrics_config.get("bert_lang", "pt") or "pt",
                verbose=False,
            )

            return format_score(float(f1[0]))

        except Exception:
            return "ERR"

    def _embedding_similarity(self, target, response):
        if not str(target).strip() or not str(response).strip():
            return "0.0000"

        try:
            target_embedding = self._ollama_embedding(str(target))
            response_embedding = self._ollama_embedding(str(response))

            return format_score(cosine_similarity(target_embedding, response_embedding))

        except Exception:
            return "ERR"

    def _ollama_embedding(self, text):
        embedding_model = (
            self.metrics_config.get("embedding_model")
            or "nomic-embed-text"
        ).strip()

        key = (embedding_model, text)

        if key in self.embedding_cache:
            return self.embedding_cache[key]

        payload = json.dumps(
            {
                "model": embedding_model,
                "prompt": text,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))

            embedding = data.get("embedding")

            if embedding is None:
                raise ValueError("No embedding returned.")

            self.embedding_cache[key] = embedding
            return embedding

        except Exception:
            payload = json.dumps(
                {
                    "model": embedding_model,
                    "input": text,
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))

            embeddings = data.get("embeddings") or []

            if not embeddings:
                raise ValueError("No embedding returned.")

            embedding = embeddings[0]
            self.embedding_cache[key] = embedding
            return embedding

    def _create_llm(self, config):
        model_type = config.get("model_type")
        model = config.get("model")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 4096)

        if model_type == "ollama":
            from langchain_community.llms import Ollama

            return Ollama(
                model=model,
                temperature=temperature,
                num_ctx=max_tokens,
            )

        raise ValueError(f"Unknown model type: {model_type}")

    def _retrieve_context(self, retriever, question):
        try:
            if hasattr(retriever, "invoke"):
                docs = retriever.invoke(question)
            else:
                docs = retriever.get_relevant_documents(question)

            text_parts = []

            for doc in docs:
                content = getattr(doc, "page_content", str(doc))

                if content:
                    text_parts.append(content)

            return "\n\n".join(text_parts)

        except Exception as exc:
            return f"[Erro ao recuperar contexto RAG: {exc}]"

    def _build_prompt(self, prompt_config, example, question, rag_context=""):
        instruction = (prompt_config.get("prompt_instruction") or "").strip()

        parts = []

        if instruction:
            parts.append(instruction)

        if rag_context:
            parts.append("Contexto recuperado pelo RAG:\n" + rag_context.strip())

        parts.append("Pergunta:\n" + question.strip())

        return "\n\n".join(parts)

    def _unique_layer_name(self, layer_name, model_name, rag_enabled, existing):
        base_name = str(layer_name).strip() or "Prompt Layer"

        if rag_enabled:
            base_name = f"{base_name} + RAG"

        if base_name not in existing:
            return base_name

        candidate = f"{base_name} ({model_name})"

        if candidate not in existing:
            return candidate

        counter = 2

        while f"{candidate} {counter}" in existing:
            counter += 1

        return f"{candidate} {counter}"


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------

class OWLLMResults(widget.OWWidget):
    name = "LLM Results"
    description = "Run multiple LLM layers and show a comparison results table"
    icon = "icons/chatbot.svg"
    priority = 110
    keywords = ["llm", "results", "metrics", "evaluation", "dataset"]

    want_main_area = True
    resizing_enabled = True

    use_response_time = settings.Setting(True)
    use_exact_match = settings.Setting(True)
    use_bleu = settings.Setting(True)
    use_rouge = settings.Setting(True)
    use_bert_score = settings.Setting(False)
    use_embedding_similarity = settings.Setting(True)
    embedding_model_name = settings.Setting("nomic-embed-text")
    bert_score_lang = settings.Setting("pt")

    class Inputs:
        llm_config = Input("LLM Config", dict, multiple=True)

    class Outputs:
        results = Output("Results", Table)

    def __init__(self):
        super().__init__()

        self.llm_configs = {}
        self.results = []
        self.layer_names = []
        self.layer_display_names = []
        self.metric_suffixes = []
        self.worker = None

        self._setup_gui()

    def _setup_gui(self):
        info_box = gui.widgetBox(self.controlArea, "LLM Configs")
        self.configs_label = gui.label(info_box, self, "Connected layers: 0")
        self.examples_label = gui.label(info_box, self, "Examples: 0")

        metrics_box = gui.widgetBox(self.controlArea, "Metrics")

        gui.checkBox(metrics_box, self, "use_response_time", label="Response time")
        gui.checkBox(metrics_box, self, "use_exact_match", label="Exact Match (EM)")
        gui.checkBox(metrics_box, self, "use_bleu", label="BLEU")
        gui.checkBox(metrics_box, self, "use_rouge", label="ROUGE-1 / ROUGE-2 / ROUGE-L")
        gui.checkBox(metrics_box, self, "use_bert_score", label="BERTScore-F1")
        gui.checkBox(metrics_box, self, "use_embedding_similarity", label="Embedding Similarity")

        gui.lineEdit(metrics_box, self, "embedding_model_name", label="Embedding model:")
        gui.lineEdit(metrics_box, self, "bert_score_lang", label="BERTScore lang:")

        self.metrics_info_label = gui.label(
            metrics_box,
            self,
            "BERTScore requires: pip install bert-score torch\n"
            "Embedding similarity requires an Ollama embedding model.",
        )
        self.metrics_info_label.setWordWrap(True)
        self.metrics_info_label.setStyleSheet("color: gray; font-size: 10px;")

        action_box = gui.widgetBox(self.controlArea, "Evaluation")

        self.run_button = gui.button(
            action_box,
            self,
            "Run Evaluation",
            callback=self.run_evaluation,
        )
        self.run_button.setEnabled(False)

        self.progress_label = gui.label(
            action_box,
            self,
            "Waiting for LLM Configs...",
        )
        self.progress_label.setWordWrap(True)

        progress_box = gui.widgetBox(self.controlArea, "Layer Progress")

        self.layer_progress_table = QTableWidget()
        self.layer_progress_table.setColumnCount(3)
        self.layer_progress_table.setHorizontalHeaderLabels(
            ["Layer", "Progress", "Status"]
        )
        self.layer_progress_table.setRowCount(0)
        self.layer_progress_table.setMinimumHeight(180)
        self.layer_progress_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layer_progress_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.layer_progress_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.layer_progress_table.horizontalHeader().setStretchLastSection(True)

        progress_box.layout().addWidget(self.layer_progress_table)

        status_box = gui.widgetBox(self.controlArea, "Status")
        self.status_label = gui.label(status_box, self, "Ready")
        self.status_label.setWordWrap(True)

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)

        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        self._setup_summary_tab()
        self._setup_details_tab()
        self._setup_raw_tab()

        self.mainArea.layout().addWidget(self.main_widget)

    def _setup_summary_tab(self):
        self.summary_tab = QWidget()
        layout = QVBoxLayout(self.summary_tab)

        title = QLabel("Summary - average metrics by layer")
        layout.addWidget(title)

        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(0)
        self.summary_table.setRowCount(0)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.summary_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.summary_table.doubleClicked.connect(
            lambda index: self.open_cell_dialog(index, self.summary_table)
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.summary_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.summary_table)

        self.tabs.addTab(self.summary_tab, "Summary")

    def _setup_details_tab(self):
        self.details_tab = QWidget()
        layout = QVBoxLayout(self.details_tab)

        title = QLabel("Question Details")
        layout.addWidget(title)

        self.question_table = QTableWidget()
        self.question_table.setColumnCount(2)
        self.question_table.setHorizontalHeaderLabels(["Row", "Question"])
        self.question_table.setRowCount(0)
        self.question_table.setMaximumHeight(160)
        self.question_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.question_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.question_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.question_table.itemSelectionChanged.connect(self.on_question_selected)
        self.question_table.doubleClicked.connect(
            lambda index: self.open_cell_dialog(index, self.question_table)
        )
        self.question_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.question_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.question_table)

        self.question_text = QTextEdit()
        self.question_text.setReadOnly(True)
        self.question_text.setMaximumHeight(90)
        layout.addWidget(self.question_text)

        self.target_text = QTextEdit()
        self.target_text.setReadOnly(True)
        self.target_text.setMaximumHeight(110)
        layout.addWidget(self.target_text)

        self.details_table = QTableWidget()
        self.details_table.setColumnCount(0)
        self.details_table.setRowCount(0)
        self.details_table.setWordWrap(True)
        self.details_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.details_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.details_table.doubleClicked.connect(
            lambda index: self.open_cell_dialog(index, self.details_table)
        )
        self.details_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.details_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.details_table)

        self.tabs.addTab(self.details_tab, "Question Details")

    def _setup_raw_tab(self):
        self.raw_tab = QWidget()
        layout = QVBoxLayout(self.raw_tab)

        title = QLabel("Raw Results - full table for export/debugging")
        layout.addWidget(title)

        self.raw_results_table = QTableWidget()
        self.raw_results_table.setColumnCount(0)
        self.raw_results_table.setRowCount(0)
        self.raw_results_table.setWordWrap(True)
        self.raw_results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.raw_results_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.raw_results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.raw_results_table.doubleClicked.connect(
            lambda index: self.open_cell_dialog(index, self.raw_results_table)
        )
        self.raw_results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.raw_results_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.raw_results_table)

        self.tabs.addTab(self.raw_tab, "Raw Results")

    def _metrics_config(self):
        return {
            "response_time": self.use_response_time,
            "exact_match": self.use_exact_match,
            "bleu": self.use_bleu,
            "rouge": self.use_rouge,
            "bert_score": self.use_bert_score,
            "embedding_similarity": self.use_embedding_similarity,
            "embedding_model": self.embedding_model_name,
            "bert_lang": self.bert_score_lang,
        }

    def _current_metric_suffixes(self):
        suffixes = []

        if self.use_response_time:
            suffixes.append("time")

        if self.use_exact_match:
            suffixes.append("EM")

        if self.use_bleu:
            suffixes.append("BLEU")

        if self.use_rouge:
            suffixes.extend(["ROUGE-1", "ROUGE-2", "ROUGE-L"])

        if self.use_bert_score:
            suffixes.append("BERTScore-F1")

        if self.use_embedding_similarity:
            suffixes.append("Embedding Similarity")

        return suffixes

    def open_cell_dialog(self, index, table=None):
        if table is None:
            table = self.sender()

        if table is None:
            return

        item = table.item(index.row(), index.column())

        if item is None:
            return

        header_item = table.horizontalHeaderItem(index.column())

        if header_item is None:
            column_name = "Column"
        else:
            column_name = header_item.text()

        value = item.text()

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Cell content - {column_name}")
        dialog.resize(900, 600)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(value)
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec_()

    @Inputs.llm_config
    def set_llm_config(self, config, id=None):
        if id is None:
            id = 0

        if config is None:
            if id in self.llm_configs:
                del self.llm_configs[id]
        else:
            self.llm_configs[id] = config

        self._update_input_info()

    def _update_input_info(self):
        configs = list(self.llm_configs.values())

        valid_configs = []
        example_count = 0

        for config in configs:
            prompt_config = config.get("prompt_config") or {}
            examples = prompt_config.get("examples", [])

            if examples:
                valid_configs.append(config)
                example_count = max(example_count, len(examples))

        self.layer_display_names = self._build_display_layer_names(valid_configs)

        self.configs_label.setText(f"Connected layers: {len(valid_configs)}")
        self.examples_label.setText(f"Examples: {example_count}")

        self._reset_layer_progress_table(
            layer_names=self.layer_display_names,
            total_examples=example_count,
        )

        if valid_configs:
            self.run_button.setEnabled(True)
            self.progress_label.setText("Ready to run evaluation")
            self.status_label.setText("LLM Configs connected")
        else:
            self.run_button.setEnabled(False)
            self.progress_label.setText("Waiting for LLM Configs...")
            self.status_label.setText("No valid input")

            self.results = []
            self.layer_names = []
            self.metric_suffixes = []

            self._clear_result_views()

            self.Outputs.results.send(None)

    def _clear_result_views(self):
        for table in [
            self.summary_table,
            self.question_table,
            self.details_table,
            self.raw_results_table,
        ]:
            table.clear()
            table.setRowCount(0)
            table.setColumnCount(0)

        self.question_text.clear()
        self.target_text.clear()

    def _build_display_layer_names(self, configs):
        names = []

        for config_index, config in enumerate(configs):
            prompt_config = config.get("prompt_config") or {}

            layer_name = config.get("layer_name") or prompt_config.get(
                "layer_name", f"Layer {config_index + 1}"
            )

            model_name = config.get("model_name", "Unknown")
            rag_enabled = (
                config.get("rag_enabled", False)
                and config.get("retriever") is not None
            )

            display_name = self._unique_layer_name(
                layer_name=layer_name,
                model_name=model_name,
                rag_enabled=rag_enabled,
                existing=names,
            )

            names.append(display_name)

        return names

    def _unique_layer_name(self, layer_name, model_name, rag_enabled, existing):
        base_name = str(layer_name).strip() or "Prompt Layer"

        if rag_enabled:
            base_name = f"{base_name} + RAG"

        if base_name not in existing:
            return base_name

        candidate = f"{base_name} ({model_name})"

        if candidate not in existing:
            return candidate

        counter = 2

        while f"{candidate} {counter}" in existing:
            counter += 1

        return f"{candidate} {counter}"

    def _reset_layer_progress_table(self, layer_names, total_examples):
        self.layer_progress_table.clear()
        self.layer_progress_table.setColumnCount(3)
        self.layer_progress_table.setHorizontalHeaderLabels(
            ["Layer", "Progress", "Status"]
        )
        self.layer_progress_table.setRowCount(len(layer_names))

        for row_idx, layer_name in enumerate(layer_names):
            self.layer_progress_table.setItem(
                row_idx,
                0,
                QTableWidgetItem(layer_name),
            )
            self.layer_progress_table.setItem(
                row_idx,
                1,
                QTableWidgetItem(f"0/{total_examples}"),
            )
            self.layer_progress_table.setItem(
                row_idx,
                2,
                QTableWidgetItem("Aguardando"),
            )

        self.layer_progress_table.resizeColumnsToContents()

    def run_evaluation(self):
        configs = list(self.llm_configs.values())

        if not configs:
            return

        self.run_button.setEnabled(False)
        self.status_label.setText("Running evaluation...")
        self.progress_label.setText("Starting...")

        valid_configs = []

        for config in configs:
            prompt_config = config.get("prompt_config") or {}
            examples = prompt_config.get("examples", [])

            if examples:
                valid_configs.append(config)

        example_count = 0

        for config in valid_configs:
            prompt_config = config.get("prompt_config") or {}
            examples = prompt_config.get("examples", [])
            example_count = max(example_count, len(examples))

        self.layer_display_names = self._build_display_layer_names(valid_configs)

        self._reset_layer_progress_table(
            layer_names=self.layer_display_names,
            total_examples=example_count,
        )

        self.metric_suffixes = self._current_metric_suffixes()

        self.worker = ResultsWorker(valid_configs, self._metrics_config())
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, layer_name, current, total, status):
        self.progress_label.setText(f"{layer_name}: {current}/{total} - {status}")

        for row_idx in range(self.layer_progress_table.rowCount()):
            item = self.layer_progress_table.item(row_idx, 0)

            if item and item.text() == layer_name:
                self.layer_progress_table.setItem(
                    row_idx,
                    1,
                    QTableWidgetItem(f"{current}/{total}"),
                )
                self.layer_progress_table.setItem(
                    row_idx,
                    2,
                    QTableWidgetItem(status),
                )
                break

        self.layer_progress_table.resizeColumnsToContents()

    def on_finished(self, rows, layer_names, metric_suffixes):
        self.results = rows
        self.layer_names = layer_names
        self.metric_suffixes = metric_suffixes

        self.progress_label.setText(f"Finished - {len(rows)} row(s)")
        self.status_label.setText("Evaluation complete")
        self.run_button.setEnabled(True)

        for row_idx in range(self.layer_progress_table.rowCount()):
            self.layer_progress_table.setItem(
                row_idx,
                2,
                QTableWidgetItem("Concluído"),
            )

        self.layer_progress_table.resizeColumnsToContents()

        self._update_all_views()
        self.commit()

    def on_error(self, message):
        self.progress_label.setText("Error")
        self.status_label.setText(f"Error: {message}")
        self.run_button.setEnabled(True)
        self.Outputs.results.send(None)

    def _table_columns(self):
        columns = ["row_index", "question", "target"]

        suffixes = self.metric_suffixes or self._current_metric_suffixes()

        for layer_name in self.layer_names:
            columns.append(layer_name)

            for suffix in suffixes:
                columns.append(layer_name + " - " + suffix)

        return columns

    def _update_all_views(self):
        self._update_summary_table()
        self._update_question_list()
        self._update_raw_table()

        if self.results:
            self.question_table.selectRow(0)
            self._update_question_details(0)

        self.tabs.setCurrentWidget(self.summary_tab)

    def _update_summary_table(self):
        metric_columns = self.metric_suffixes or self._current_metric_suffixes()

        summary_headers = ["Layer"]
        summary_headers.extend(metric_columns)

        self.summary_table.clear()
        self.summary_table.setColumnCount(len(summary_headers))
        self.summary_table.setRowCount(len(self.layer_names))
        self.summary_table.setHorizontalHeaderLabels(summary_headers)

        for row_idx, layer_name in enumerate(self.layer_names):
            self.summary_table.setItem(row_idx, 0, QTableWidgetItem(layer_name))

            for col_idx, metric in enumerate(metric_columns, 1):
                avg_value = self._average_metric(layer_name, metric)
                self.summary_table.setItem(row_idx, col_idx, QTableWidgetItem(avg_value))

        self.summary_table.resizeColumnsToContents()

        for col_idx, header in enumerate(summary_headers):
            if header == "Layer":
                self.summary_table.setColumnWidth(col_idx, 260)
            else:
                self.summary_table.setColumnWidth(col_idx, 130)

    def _average_metric(self, layer_name, metric):
        values = []

        column = layer_name + " - " + metric

        for row in self.results:
            raw_value = row.get(column, "")

            if metric == "time":
                value = parse_time_seconds(raw_value)
            else:
                value = safe_float(raw_value)

            if value is not None:
                values.append(value)

        if not values:
            return "ERR" if self._has_error_values(column) else ""

        avg = sum(values) / len(values)

        if metric == "time":
            return f"{avg:.3f}s"

        return f"{avg:.4f}"

    def _has_error_values(self, column):
        for row in self.results:
            if str(row.get(column, "")).strip().upper() == "ERR":
                return True

        return False

    def _update_question_list(self):
        self.question_table.clear()
        self.question_table.setColumnCount(2)
        self.question_table.setHorizontalHeaderLabels(["Row", "Question"])
        self.question_table.setRowCount(len(self.results))

        for row_idx, row in enumerate(self.results):
            self.question_table.setItem(
                row_idx,
                0,
                QTableWidgetItem(str(row.get("row_index", ""))),
            )
            self.question_table.setItem(
                row_idx,
                1,
                QTableWidgetItem(str(row.get("question", ""))),
            )

        self.question_table.resizeColumnsToContents()
        self.question_table.setColumnWidth(0, 70)
        self.question_table.setColumnWidth(1, 700)

    def on_question_selected(self):
        selected_rows = self.question_table.selectionModel().selectedRows()

        if not selected_rows:
            return

        row_idx = selected_rows[0].row()
        self._update_question_details(row_idx)

    def _update_question_details(self, row_idx):
        if row_idx < 0 or row_idx >= len(self.results):
            return

        row = self.results[row_idx]

        question = str(row.get("question", ""))
        target = str(row.get("target", ""))

        self.question_text.setPlainText("Question:\n" + question)
        self.target_text.setPlainText("Target:\n" + target)

        metric_columns = self.metric_suffixes or self._current_metric_suffixes()

        headers = ["Layer", "Response"]
        headers.extend(metric_columns)

        self.details_table.clear()
        self.details_table.setColumnCount(len(headers))
        self.details_table.setRowCount(len(self.layer_names))
        self.details_table.setHorizontalHeaderLabels(headers)

        for layer_idx, layer_name in enumerate(self.layer_names):
            self.details_table.setItem(
                layer_idx,
                0,
                QTableWidgetItem(layer_name),
            )

            self.details_table.setItem(
                layer_idx,
                1,
                QTableWidgetItem(str(row.get(layer_name, ""))),
            )

            for col_idx, metric in enumerate(metric_columns, 2):
                column = layer_name + " - " + metric
                self.details_table.setItem(
                    layer_idx,
                    col_idx,
                    QTableWidgetItem(str(row.get(column, ""))),
                )

        self.details_table.resizeColumnsToContents()
        self.details_table.resizeRowsToContents()

        self.details_table.setColumnWidth(0, 240)
        self.details_table.setColumnWidth(1, 520)

        for col_idx in range(2, len(headers)):
            self.details_table.setColumnWidth(col_idx, 120)

    def _update_raw_table(self):
        columns = self._table_columns()

        self.raw_results_table.clear()
        self.raw_results_table.setColumnCount(len(columns))
        self.raw_results_table.setRowCount(len(self.results))
        self.raw_results_table.setHorizontalHeaderLabels(columns)

        for row_idx, row in enumerate(self.results):
            for col_idx, column in enumerate(columns):
                value = str(row.get(column, ""))
                item = QTableWidgetItem(value)
                self.raw_results_table.setItem(row_idx, col_idx, item)

        self.raw_results_table.resizeColumnsToContents()
        self.raw_results_table.resizeRowsToContents()

        for col_idx, column in enumerate(columns):
            if column == "row_index":
                self.raw_results_table.setColumnWidth(col_idx, 80)
            elif column == "question":
                self.raw_results_table.setColumnWidth(col_idx, 280)
            elif column == "target":
                self.raw_results_table.setColumnWidth(col_idx, 320)
            elif column.endswith("time"):
                self.raw_results_table.setColumnWidth(col_idx, 90)
            elif any(
                column.endswith(metric)
                for metric in [
                    "EM",
                    "BLEU",
                    "ROUGE-1",
                    "ROUGE-2",
                    "ROUGE-L",
                    "BERTScore-F1",
                    "Embedding Similarity",
                ]
            ):
                self.raw_results_table.setColumnWidth(col_idx, 120)
            elif col_idx >= 3:
                self.raw_results_table.setColumnWidth(col_idx, 420)

    def commit(self):
        if not self.results:
            self.Outputs.results.send(None)
            return

        columns = self._table_columns()
        meta_vars = [StringVariable(column) for column in columns]

        domain = Domain([], metas=meta_vars)

        metas = np.array(
            [
                [str(row.get(column, "")) for column in columns]
                for row in self.results
            ],
            dtype=object,
        )

        table = Table.from_numpy(
            domain,
            X=np.empty((len(self.results), 0)),
            metas=metas,
        )

        self.Outputs.results.send(table)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(OWLLMResults).run()