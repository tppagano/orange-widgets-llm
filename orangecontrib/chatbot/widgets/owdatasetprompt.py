"""
Orange3 Dataset Prompt Widget
=============================

Widget for selecting question/target columns and creating dynamic prompt instructions
from a tabular dataset.
"""

from AnyQt.QtWidgets import QTextEdit

from Orange.data import Table
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


class OWDatasetPrompt(widget.OWWidget):
    name = "Dataset Prompt"
    description = "Prepare question/answer datasets and dynamic prompt instructions for LLMs"
    icon = "icons/chatbot.svg"
    priority = 85
    keywords = ["dataset", "prompt", "llm", "evaluation"]

    want_main_area = False
    resizing_enabled = False

    question_column_index = settings.Setting(0)
    answer_column_index = settings.Setting(1)

    layer_name = settings.Setting("Prompt Layer")
    prompt_instruction = settings.Setting(
        "Responda de forma clara e objetiva."
    )

    class Inputs:
        data = Input("Data", Table, default=True)

    class Outputs:
        prompt_config = Output("Prompt Config", dict)

    def __init__(self):
        super().__init__()

        self.data = None
        self.column_vars = []
        self.column_names = []
        self.examples = []

        self._setup_gui()

    def _setup_gui(self):
        info_box = gui.widgetBox(self.controlArea, "Dataset Info")
        self.info_label = gui.label(info_box, self, "No dataset loaded")

        columns_box = gui.widgetBox(self.controlArea, "Column Selection")

        self.question_combo = gui.comboBox(
            columns_box,
            self,
            "question_column_index",
            label="Question column:",
            items=[],
            callback=self.on_column_changed,
        )

        self.answer_combo = gui.comboBox(
            columns_box,
            self,
            "answer_column_index",
            label="Target/expected answer column:",
            items=[],
            callback=self.on_column_changed,
        )

        prompt_box = gui.widgetBox(self.controlArea, "Dynamic Prompt")

        gui.lineEdit(
            prompt_box,
            self,
            "layer_name",
            label="Layer name:",
            callback=self.on_prompt_changed,
        )

        instruction_label = gui.label(
            prompt_box,
            self,
            "Prompt instructions:"
        )
        instruction_label.setWordWrap(True)

        self.prompt_editor = QTextEdit()
        self.prompt_editor.setPlainText(self.prompt_instruction)
        self.prompt_editor.setMinimumHeight(120)
        prompt_box.layout().addWidget(self.prompt_editor)

        help_label = gui.label(
            prompt_box,
            self,
            "Digite apenas a instrução para a LLM. "
            "A pergunta do dataset será adicionada automaticamente."
        )
        help_label.setWordWrap(True)

        preview_box = gui.widgetBox(self.controlArea, "Preview")
        self.preview_label = gui.label(preview_box, self, "Waiting for data...")
        self.preview_label.setWordWrap(True)

        status_box = gui.widgetBox(self.controlArea, "Status")
        self.status_label = gui.label(status_box, self, "Ready")

        self.question_combo.setEnabled(False)
        self.answer_combo.setEnabled(False)

        self.prompt_editor.textChanged.connect(self.on_prompt_changed)

    @Inputs.data
    def set_data(self, data):
        """Receive dataset from Orange."""

        self.data = data
        self.column_vars = []
        self.column_names = []
        self.examples = []

        if data is None:
            self.info_label.setText("No dataset loaded")
            self.preview_label.setText("Waiting for data...")
            self.status_label.setText("No input data")
            self._update_combos([])
            self.Outputs.prompt_config.send(None)
            return

        self.column_vars = (
            list(data.domain.attributes)
            + list(data.domain.class_vars)
            + list(data.domain.metas)
        )

        self.column_names = [var.name for var in self.column_vars]

        self._choose_default_columns()
        self._update_combos(self.column_names)

        self.info_label.setText(
            f"{len(data)} rows loaded | {len(self.column_names)} columns available"
        )

        self.status_label.setText("Dataset loaded")
        self.on_column_changed()

    def _choose_default_columns(self):
        """Try to automatically choose question/target columns."""

        if not self.column_names:
            self.question_column_index = 0
            self.answer_column_index = 0
            return

        lower_names = [name.lower() for name in self.column_names]

        question_candidates = ["pergunta", "question", "prompt"]
        answer_candidates = [
            "resposta",
            "answer",
            "expected_answer",
            "resposta_esperada",
            "target",
            "label",
        ]

        self.question_column_index = 0
        self.answer_column_index = 1 if len(self.column_names) > 1 else 0

        for candidate in question_candidates:
            if candidate in lower_names:
                self.question_column_index = lower_names.index(candidate)
                break

        for candidate in answer_candidates:
            if candidate in lower_names:
                self.answer_column_index = lower_names.index(candidate)
                break

    def _update_combos(self, items):
        """Update combo boxes with available columns."""

        self.question_combo.blockSignals(True)
        self.answer_combo.blockSignals(True)

        self.question_combo.clear()
        self.answer_combo.clear()

        self.question_combo.addItems(items)
        self.answer_combo.addItems(items)

        has_items = bool(items)

        self.question_combo.setEnabled(has_items)
        self.answer_combo.setEnabled(has_items)

        if has_items:
            self.question_column_index = max(
                0, min(self.question_column_index, len(items) - 1)
            )
            self.answer_column_index = max(
                0, min(self.answer_column_index, len(items) - 1)
            )

            self.question_combo.setCurrentIndex(self.question_column_index)
            self.answer_combo.setCurrentIndex(self.answer_column_index)

        self.question_combo.blockSignals(False)
        self.answer_combo.blockSignals(False)

    def on_column_changed(self):
        """Update examples, preview and output when selected columns change."""

        if self.data is None or not self.column_vars:
            self.Outputs.prompt_config.send(None)
            return

        self.question_column_index = max(
            0, min(self.question_column_index, len(self.column_vars) - 1)
        )
        self.answer_column_index = max(
            0, min(self.answer_column_index, len(self.column_vars) - 1)
        )

        question_var = self.column_vars[self.question_column_index]
        answer_var = self.column_vars[self.answer_column_index]

        self.examples = []

        for row_index, row in enumerate(self.data):
            question = self._cell_to_text(row, question_var)
            expected_answer = self._cell_to_text(row, answer_var)

            if question:
                rendered_prompt = self._render_prompt(
                    question=question,
                    row_index=row_index,
                    rag_context=""
                )

                self.examples.append(
                    {
                        "row_index": row_index,
                        "question": question,
                        "expected_answer": expected_answer,
                        "rendered_prompt": rendered_prompt,
                    }
                )

        self._update_preview()
        self.commit()

    def on_prompt_changed(self):
        """Update prompt instruction and refresh preview/output."""

        if hasattr(self, "prompt_editor"):
            self.prompt_instruction = self.prompt_editor.toPlainText()

        if self.data is not None:
            self.on_column_changed()
        else:
            self.commit()

    def _render_prompt(self, question, row_index=None, rag_context=""):
        """Build the final prompt automatically."""

        instruction = (self.prompt_instruction or "").strip()

        parts = []

        if instruction:
            parts.append(instruction)

        if rag_context:
            parts.append("Contexto recuperado pelo RAG:\n" + rag_context.strip())

        parts.append("Pergunta:\n" + question.strip())

        return "\n\n".join(parts)

    def _update_preview(self):
        """Show the first generated prompt as preview."""

        if self.examples:
            first = self.examples[0]
            preview = (
                "First generated prompt:\n\n"
                f"{first['rendered_prompt'][:600]}\n\n"
                "Target/expected answer preview:\n"
                f"{first['expected_answer'][:200]}"
            )
        else:
            preview = "No valid questions found."

        self.preview_label.setText(preview)
        self.status_label.setText(
            f"Ready - {len(self.examples)} prompt(s) generated"
        )

    def _cell_to_text(self, row, var):
        """Convert an Orange table cell to clean text."""

        try:
            value = row[var]
            text = str(value).strip()

            if text in ("", "?") or text.lower() == "nan":
                return ""

            return text

        except Exception:
            return ""

    def commit(self):
        """Send prompt configuration to output."""

        if self.data is None or not self.column_vars:
            self.Outputs.prompt_config.send(None)
            return

        question_var = self.column_vars[self.question_column_index]
        answer_var = self.column_vars[self.answer_column_index]

        prompt_config = {
            "layer_name": self.layer_name,
            "question_column": question_var.name,
            "answer_column": answer_var.name,
            "prompt_instruction": self.prompt_instruction,
            "examples": self.examples,
            "total_examples": len(self.examples),
        }

        self.Outputs.prompt_config.send(prompt_config)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(OWDatasetPrompt).run()