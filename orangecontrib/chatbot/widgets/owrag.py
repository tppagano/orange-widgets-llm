"""
Orange3 RAG Widget
==================

Widget for Retrieval-Augmented Generation document processing.
Vectorizes documents and provides retrieval capabilities.
"""

import os

from AnyQt.QtWidgets import QFileDialog
from AnyQt.QtCore import QThread, pyqtSignal

from Orange.data import Table
from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


class VectorizeWorker(QThread):
    """Worker thread for document vectorization"""
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(object, int, int)  # vector_store, added_count, skipped_count
    error = pyqtSignal(str)
    
    def __init__(self, documents):
        super().__init__()
        self.documents = documents
        
    def run(self):
        try:
            from orangecontrib.chatbot.rag_backend import (
                get_vector_store, get_text_splitter, 
                persist_vector_store, add_documents_with_tracking
            )
            
            vector_store = get_vector_store()
            text_splitter = get_text_splitter()
            
            total = len(self.documents)
            total_added = 0
            total_skipped = 0
            
            for i, doc_text in enumerate(self.documents):
                # Split document
                splits = text_splitter.split_text(doc_text)
                
                # Create list of (text, metadata) tuples for tracking
                docs_with_metadata = [
                    (split, {"source": f"document_{i}", "chunk": j}) 
                    for j, split in enumerate(splits)
                ]
                
                # Add documents with duplicate checking
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
    
    # Settings
    chunk_size = settings.Setting(500)
    chunk_overlap = settings.Setting(50)
    top_k = settings.Setting(2)
    
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
        
        self._setup_gui()
        
        # Check for existing vectors
        self._check_existing_vectors()
    
    def _setup_gui(self):
        # Vector Store Status box
        store_box = gui.widgetBox(self.controlArea, "Vector Store Status")
        self.store_info_label = gui.label(store_box, self, "Checking...")
        
        gui.button(
            store_box, self, "Clear Vector Store",
            callback=self.clear_vector_store
        )
        
        # File loading box
        file_box = gui.widgetBox(self.controlArea, "Load Documents")
        gui.button(
            file_box, self, "Load PDF/Text Files",
            callback=self.load_files
        )
        
        # Info box
        info_box = gui.widgetBox(self.controlArea, "Document Info")
        self.info_label = gui.label(info_box, self, "No documents loaded")
        
        # Settings box
        settings_box = gui.widgetBox(self.controlArea, "Vectorization Settings")
        
        gui.spin(
            settings_box, self, "chunk_size",
            minv=100, maxv=2000, step=50,
            label="Chunk size:",
            callback=self.on_settings_changed
        )
        
        gui.spin(
            settings_box, self, "chunk_overlap",
            minv=0, maxv=500, step=10,
            label="Chunk overlap:",
            callback=self.on_settings_changed
        )
        
        gui.spin(
            settings_box, self, "top_k",
            minv=1, maxv=10, step=1,
            label="Top-K results:",
            callback=self.on_settings_changed
        )
        
        # Vectorization box
        vec_box = gui.widgetBox(self.controlArea, "Vectorization")
        self.vectorize_btn = gui.button(
            vec_box, self, "Vectorize Documents",
            callback=self.vectorize_documents
        )
        self.vectorize_btn.setEnabled(False)
        
        self.progress_label = gui.label(vec_box, self, "")
        
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
                    f"✓ {doc_count} documents in vector store"
                )
                # Load the vector store and retriever
                self.vector_store = get_vector_store()
                self.retriever = self.vector_store.as_retriever(
                    search_kwargs={"k": self.top_k}
                )
                # Send the retriever output
                self.Outputs.retriever.send(self.retriever)
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
                if file_path.lower().endswith('.pdf'):
                    # Extract text from PDF
                    text = self._extract_pdf_text(file_path)
                    if text.strip():
                        self.documents.append(text)
                        loaded_count += 1
                elif file_path.lower().endswith('.txt'):
                    # Read text file
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                        if text.strip():
                            self.documents.append(text)
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
        for row in data:
            text_parts = []
            for var in data.domain.metas + data.domain.attributes:
                if var.is_string:
                    val = str(row[var])
                    if val and val.strip():
                        text_parts.append(val)
            if text_parts:
                self.documents.append(" ".join(text_parts))
        
        # Update UI
        doc_count = len(self.documents)
        self.info_label.setText(f"{doc_count} documents loaded")
        self.info.set_input_summary(f"{doc_count} documents")
        self.vectorize_btn.setEnabled(doc_count > 0)
        self.status_label.setText(f"Loaded {doc_count} documents")
    
    def on_settings_changed(self):
        """Handle settings changes"""
        if self.vector_store is not None:
            self.status_label.setText("Settings changed - re-vectorize to apply")
    
    def vectorize_documents(self):
        """Start vectorization process"""
        if not self.documents:
            return
        
        self.vectorize_btn.setEnabled(False)
        self.status_label.setText("Vectorizing...")
        self.progress_label.setText("Starting...")
        
        self.worker = VectorizeWorker(self.documents)
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
        
        # Create retriever with current settings
        self.retriever = vector_store.as_retriever(
            search_kwargs={"k": self.top_k}
        )
        
        # Update vector store info
        try:
            from orangecontrib.chatbot.rag_backend import get_vector_store_doc_count
            doc_count = get_vector_store_doc_count()
            self.store_info_label.setText(
                f"✓ {doc_count} documents in vector store"
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
        
        # Send outputs
        self.Outputs.retriever.send(self.retriever)
    
    def on_vectorize_error(self, error_msg):
        """Handle vectorization error"""
        self.progress_label.setText(f"✗ Error: {error_msg}")
        self.status_label.setText("Error during vectorization")
        self.vectorize_btn.setEnabled(True)
        
        self.Outputs.retriever.send(None)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWRAG).run()
