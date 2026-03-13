"""
Orange3 RAG Widget
==================

Widget for Retrieval-Augmented Generation document processing.
Vectorizes documents and provides retrieval capabilities.
"""

import os
import hashlib

from AnyQt.QtWidgets import QFileDialog, QWidget, QHBoxLayout, QVBoxLayout
from AnyQt.QtCore import QThread, pyqtSignal

from Orange.data import Table
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


class VectorizeWorker(QThread):
    """Worker thread for document vectorization"""
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(object, int, int)  # vector_store, added_count, skipped_count
    error = pyqtSignal(str)

    def __init__(self, documents, chunk_size=500, chunk_overlap=75):
        super().__init__()
        self.documents = documents
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def run(self):
        try:
            from orangecontrib.chatbot.rag_backend import (
                get_vector_store, get_text_splitter, semantic_split,
                persist_vector_store, add_documents_with_tracking
            )

            vector_store = get_vector_store()
            text_splitter = get_text_splitter(self.chunk_size, self.chunk_overlap)

            total = len(self.documents)
            total_added = 0
            total_skipped = 0

            for i, doc in enumerate(self.documents):
                # Primary: semantic split (headings, paragraphs, sections, lists)
                semantic_units = semantic_split(doc["text"])

                # Secondary: apply size-based splitter to each semantic unit
                splits = []
                for unit in semantic_units:
                    splits.extend(text_splitter.split_text(unit))

                # Build (text, metadata) tuples
                docs_with_metadata = [
                    (split, {"doc_id": doc["doc_id"], "doc_label": doc["doc_label"], "chunk": j})
                    for j, split in enumerate(splits)
                ]

                added, skipped = add_documents_with_tracking(docs_with_metadata)
                total_added += added
                total_skipped += skipped

                self.progress.emit(i + 1, total)

            self.finished.emit(vector_store, total_added, total_skipped)
        except Exception as e:
            self.error.emit(str(e))


class OWRAG(widget.OWWidget):
    name = "RAG"
    description = "Document vectorization and retrieval for RAG"
    icon = "icons/rag.svg"
    priority = 80
    keywords = ["rag", "retrieval", "vector", "embeddings"]
    
    want_main_area = False
    resizing_enabled = False
    
    # Retrieval presets: 0=Precise, 1=Balanced, 2=Deep research
    PRESETS = [
        {"label": "Precise answers",  "chunk_size": 300, "chunk_overlap": 50,  "top_k": 4},
        {"label": "Balanced",         "chunk_size": 500, "chunk_overlap": 75,  "top_k": 5},
        {"label": "Deep research",    "chunk_size": 900, "chunk_overlap": 120, "top_k": 8},
    ]

    # Settings
    retrieval_preset = settings.Setting(1)  # default: Balanced
    chunk_size = settings.Setting(500)
    chunk_overlap = settings.Setting(75)
    top_k = settings.Setting(5)
    selected_doc_index = settings.Setting(0)
    show_advanced = settings.Setting(False)
    
    class Inputs:
        documents = Input("Documents", Table, default=True)
    
    class Outputs:
        retriever = Output("Retriever", object)
    
    def __init__(self):
        super().__init__()
        
        self.documents = []
        self.vector_store = None
        self.retriever = None
        self.worker = None
        self.available_documents = []
        
        self._setup_gui()
        
        # Check for existing vectors
        self._check_existing_vectors()
    
    def _setup_gui(self):
        # Main content in two side-by-side columns for a shorter/wider widget.
        top_row = QWidget(self.controlArea)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(6)
        self.controlArea.layout().addWidget(top_row)

        left_col = QWidget(top_row)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        top_row_layout.addWidget(left_col, 1)

        right_col = QWidget(top_row)
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        top_row_layout.addWidget(right_col, 1)

        # Left column
        store_box = gui.widgetBox(left_col, "Vector Store Status")
        left_layout.addWidget(store_box)
        self.store_info_label = gui.label(store_box, self, "Checking...")

        gui.button(
            store_box, self, "Clear Vector Store",
            callback=self.clear_vector_store
        )

        file_box = gui.widgetBox(left_col, "Load Documents")
        left_layout.addWidget(file_box)
        gui.button(
            file_box, self, "Load PDF/Text Files",
            callback=self.load_files
        )

        info_box = gui.widgetBox(left_col, "Document Info")
        left_layout.addWidget(info_box)
        self.info_label = gui.label(info_box, self, "No documents loaded")

        # Right column
        preset_box = gui.widgetBox(right_col, "Retrieval Mode")
        right_layout.addWidget(preset_box)
        self.preset_box = preset_box
        gui.radioButtons(
            preset_box, self, "retrieval_preset",
            btnLabels=[p["label"] for p in self.PRESETS],
            callback=self.on_preset_changed,
        )

        vec_box = gui.widgetBox(right_col, "Vectorization")
        right_layout.addWidget(vec_box)
        self.vectorize_btn = gui.button(
            vec_box, self, "Vectorize Documents",
            callback=self.vectorize_documents
        )
        self.vectorize_btn.setEnabled(False)
        self.progress_label = gui.label(vec_box, self, "")

        filter_box = gui.widgetBox(right_col, "Source Filter")
        right_layout.addWidget(filter_box)
        self.doc_combo = gui.comboBox(
            filter_box, self, "selected_doc_index",
            label="Retrieve from:",
            items=["All documents"],
            callback=self.on_doc_selection_changed,
        )

        # Allow columns to compact naturally.
        left_layout.addStretch(1)
        right_layout.addStretch(1)

        # Advanced settings (near bottom)
        gui.checkBox(
            self.controlArea, self, "show_advanced",
            label="Show advanced settings",
            callback=self.on_advanced_visibility_changed,
        )

        self.adv_inner = gui.widgetBox(self.controlArea, "Advanced Settings")

        gui.spin(
            self.adv_inner, self, "chunk_size",
            minv=100, maxv=2000, step=50,
            label="Chunk size:",
            callback=self.on_settings_changed
        )

        gui.spin(
            self.adv_inner, self, "chunk_overlap",
            minv=0, maxv=500, step=10,
            label="Chunk overlap:",
            callback=self.on_settings_changed
        )

        gui.spin(
            self.adv_inner, self, "top_k",
            minv=1, maxv=10, step=1,
            label="Top-K results:",
            callback=self.on_settings_changed
        )
        self.adv_inner.setVisible(self.show_advanced)
        self.preset_box.setEnabled(not self.show_advanced)
        
        # Status box
        status_box = gui.widgetBox(self.controlArea, "Status")
        self.status_label = gui.label(status_box, self, "Ready")
    
    def _check_existing_vectors(self):
        """Check if vector store has existing documents"""
        try:
            from orangecontrib.chatbot.rag_backend import (
                get_vector_store_doc_count, get_vector_store
            )
            
            doc_count = get_vector_store_doc_count()
            if doc_count > 0:
                self.store_info_label.setText(
                    f"✓ {doc_count} chunks in vector store"
                )
                # Load the vector store, refresh doc list, and send filtered retriever
                self.vector_store = get_vector_store()
                self._refresh_document_list()
                self._build_and_send_retriever()
                self.status_label.setText("Loaded existing vectors")
            else:
                self.store_info_label.setText("No documents in vector store")
                self.status_label.setText("Ready")
        except Exception as e:
            self.store_info_label.setText(f"Error checking store: {str(e)}")
            self.status_label.setText("Ready")
    
    def clear_vector_store(self):
        """Clear all documents from the vector store"""
        try:
            from orangecontrib.chatbot.rag_backend import clear_vector_store
            
            if clear_vector_store():
                self.vector_store = None
                self.retriever = None
                self._refresh_document_list()
                self.store_info_label.setText("✓ Vector store cleared")
                self.status_label.setText("Vector store cleared")
                self.Outputs.retriever.send(None)
            else:
                self.status_label.setText("Error clearing vector store")
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
    
    def load_files(self):
        """Open file dialog and load PDF/text files"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF or Text Files",
            os.path.expanduser("~"),
            "Documents (*.pdf *.txt);;PDF Files (*.pdf);;Text Files (*.txt);;All Files (*)"
        )
        
        if not file_paths:
            return
        
        self.documents = []
        loaded_count = 0
        
        for file_path in file_paths:
            try:
                doc_id = "file:" + os.path.normpath(os.path.abspath(file_path))
                doc_label = os.path.basename(file_path)
                
                if file_path.lower().endswith('.pdf'):
                    # Extract text from PDF
                    text = self._extract_pdf_text(file_path)
                    if text.strip():
                        self.documents.append({"doc_id": doc_id, "doc_label": doc_label, "text": text})
                        loaded_count += 1
                elif file_path.lower().endswith('.txt'):
                    # Read text file
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                        if text.strip():
                            self.documents.append({"doc_id": doc_id, "doc_label": doc_label, "text": text})
                            loaded_count += 1
            except Exception as e:
                self.status_label.setText(f"Error loading {os.path.basename(file_path)}: {str(e)}")
        
        # Update UI
        if loaded_count > 0:
            self.info_label.setText(f"{loaded_count} documents loaded from files")
            self.info.set_input_summary(f"{loaded_count} files")
            self.vectorize_btn.setEnabled(True)
            self.status_label.setText(f"Loaded {loaded_count} files")
        else:
            self.status_label.setText("No valid documents loaded")
    
    def _extract_pdf_text(self, pdf_path):
        """Extract text from a PDF file"""
        from pypdf import PdfReader
        
        reader = PdfReader(pdf_path)
        text_parts = []
        
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    @Inputs.documents
    def set_documents(self, data):
        """Handle input documents"""
        
        if data is None:
            # Don't clear documents if loaded from files
            if not self.documents:
                self.info_label.setText("No documents loaded")
                self.status_label.setText("Ready")
                self.vectorize_btn.setEnabled(False)
            self.info.set_input_summary(self.info.NoInput)
            return
        
        # Extract text from documents
        self.documents = []
        for i, row in enumerate(data):
            text_parts = []
            for var in data.domain.metas + data.domain.attributes:
                if var.is_string:
                    val = str(row[var])
                    if val and val.strip():
                        text_parts.append(val)
            if text_parts:
                text = " ".join(text_parts)
                doc_id = "row:" + hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]
                preview = text[:50] + "..." if len(text) > 50 else text
                doc_label = f"Row {i + 1}: {preview}"
                self.documents.append({"doc_id": doc_id, "doc_label": doc_label, "text": text})
        
        # Update UI
        doc_count = len(self.documents)
        self.info_label.setText(f"{doc_count} documents loaded")
        self.info.set_input_summary(f"{doc_count} documents")
        self.vectorize_btn.setEnabled(doc_count > 0)
        self.status_label.setText(f"Loaded {doc_count} documents")
    
    def on_preset_changed(self):
        """Apply the selected retrieval preset to the advanced settings"""
        preset = self.PRESETS[self.retrieval_preset]
        self.chunk_size = preset["chunk_size"]
        self.chunk_overlap = preset["chunk_overlap"]
        self.top_k = preset["top_k"]
        if self.vector_store is not None:
            self.status_label.setText(
                f"Preset '{preset['label']}' applied - re-vectorize to update chunk settings"
            )
            self._build_and_send_retriever()

    def on_settings_changed(self):
        """Handle manual advanced settings changes"""
        if self.vector_store is not None:
            self.status_label.setText("Settings changed - re-vectorize to apply chunk settings")
            self._build_and_send_retriever()
    
    def vectorize_documents(self):
        """Start vectorization process"""
        if not self.documents:
            return
        
        self.vectorize_btn.setEnabled(False)
        self.status_label.setText("Vectorizing...")
        self.progress_label.setText("Starting...")
        
        self.worker = VectorizeWorker(
            self.documents,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self.worker.progress.connect(self.on_vectorize_progress)
        self.worker.finished.connect(self.on_vectorize_finished)
        self.worker.error.connect(self.on_vectorize_error)
        self.worker.start()
    
    def on_vectorize_progress(self, current, total):
        """Update progress"""
        self.progress_label.setText(f"Vectorizing: {current}/{total}")
    
    def on_vectorize_finished(self, vector_store, added_count, skipped_count):
        """Handle vectorization completion"""
        self.vector_store = vector_store
        
        # Refresh document list and rebuild filtered retriever
        self._refresh_document_list()
        self._build_and_send_retriever()
        
        # Update vector store info
        try:
            from orangecontrib.chatbot.rag_backend import get_vector_store_doc_count
            doc_count = get_vector_store_doc_count()
            self.store_info_label.setText(
                f"✓ {doc_count} chunks in vector store"
            )
        except Exception:
            pass
        
        # Show results including duplicates skipped
        if skipped_count > 0:
            self.progress_label.setText(
                f"✓ Added {added_count} chunks, skipped {skipped_count} duplicates"
            )
            self.status_label.setText(
                f"Ready - {added_count} new chunks added, {skipped_count} duplicates skipped"
            )
        else:
            self.progress_label.setText(f"✓ Vectorization complete - {added_count} chunks added")
            self.status_label.setText(f"Ready - {added_count} chunks vectorized")
        
        self.vectorize_btn.setEnabled(True)
    
    def on_vectorize_error(self, error_msg):
        """Handle vectorization error"""
        self.progress_label.setText(f"✗ Error: {error_msg}")
        self.status_label.setText("Error during vectorization")
        self.vectorize_btn.setEnabled(True)
        
        self.Outputs.retriever.send(None)

    def _refresh_document_list(self):
        """Refresh the document selector combo box from the vector store"""
        try:
            from orangecontrib.chatbot.rag_backend import get_indexed_documents
            self.available_documents = get_indexed_documents()
        except Exception:
            self.available_documents = []
        
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()
        self.doc_combo.addItem("All documents")
        for _, label in self.available_documents:
            self.doc_combo.addItem(label)
        
        max_idx = len(self.available_documents)
        if self.selected_doc_index > max_idx:
            self.selected_doc_index = 0
        self.doc_combo.setCurrentIndex(self.selected_doc_index)
        self.doc_combo.blockSignals(False)

    def _build_and_send_retriever(self):
        """Build a retriever with an optional source filter and send it as output"""
        if self.vector_store is None:
            return
        search_kwargs = {"k": self.top_k}
        if self.selected_doc_index > 0 and self.available_documents:
            idx = self.selected_doc_index - 1
            if idx < len(self.available_documents):
                doc_id = self.available_documents[idx][0]
                search_kwargs["filter"] = {"doc_id": doc_id}
        self.retriever = self.vector_store.as_retriever(search_kwargs=search_kwargs)
        self.Outputs.retriever.send(self.retriever)

    def on_doc_selection_changed(self):
        """Rebuild and send retriever when the selected source document changes"""
        if self.vector_store is not None:
            self._build_and_send_retriever()

    def on_advanced_visibility_changed(self):
        """Show/hide advanced settings panel"""
        if hasattr(self, "adv_inner"):
            self.adv_inner.setVisible(self.show_advanced)
        if hasattr(self, "preset_box"):
            self.preset_box.setEnabled(not self.show_advanced)
        # When advanced is turned off, enforce selected preset values again.
        if not self.show_advanced:
            self.on_preset_changed()


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWRAG).run()
