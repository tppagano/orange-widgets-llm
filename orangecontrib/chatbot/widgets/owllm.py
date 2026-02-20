"""
Orange3 LLM Widget
==================

Widget for Language Model configuration and inference.
"""

from Orange.widgets import widget, gui, settings
from Orange.widgets.widget import Input, Output


LLM_OPTIONS = {
    "gemma3": {"type": "ollama", "model": "gemma3"},
    "llama3.1:8b": {"type": "ollama", "model": "llama3.1:8b"},
    "gpt-4o-mini": {"type": "openai", "model": "gpt-4o-mini"},
    "gpt-4o": {"type": "openai", "model": "gpt-4o"},
}


class OWLLM(widget.OWWidget):
    name = "LLM"
    description = "Language Model configuration for chat"
    icon = "icons/llm.svg"
    priority = 90
    keywords = ["llm", "language model", "ai", "gpt", "ollama"]
    
    want_main_area = False
    resizing_enabled = False
    
    # Settings
    selected_llm = settings.Setting(1)  # Index into LLM_OPTIONS
    temperature = settings.Setting(0.7)
    max_tokens = settings.Setting(4096)
    streaming = settings.Setting(True)
    
    class Inputs:
        retriever = Input("Retriever", object)
    
    class Outputs:
        llm_config = Output("LLM Config", dict)
    
    def __init__(self):
        super().__init__()
        
        self.retriever = None
        self.llm_config = None
        
        self._setup_gui()
        self._update_config()
    
    def _setup_gui(self):
        # Model selection
        model_box = gui.widgetBox(self.controlArea, "Model Selection")
        
        gui.comboBox(
            model_box, self, "selected_llm",
            label="Model:",
            items=list(LLM_OPTIONS.keys()),
            callback=self._update_config
        )
        
        self.model_info_label = gui.label(model_box, self, "")
        self._update_model_info()
        
        # Parameters
        params_box = gui.widgetBox(self.controlArea, "Parameters")
        
        gui.doubleSpin(
            params_box, self, "temperature",
            minv=0.0, maxv=2.0, step=0.1,
            label="Temperature:",
            callback=self._update_config
        )
        
        gui.spin(
            params_box, self, "max_tokens",
            minv=512, maxv=32768, step=512,
            label="Max tokens:",
            callback=self._update_config
        )
        
        gui.checkBox(
            params_box, self, "streaming",
            label="Enable streaming",
            callback=self._update_config
        )
        
        # RAG status
        rag_box = gui.widgetBox(self.controlArea, "RAG Status")
        self.rag_status_label = gui.label(rag_box, self, "Waiting for retriever...")
        
        # Info
        info_box = gui.widgetBox(self.controlArea, "Info")
        self.info_label = gui.label(
            info_box, self,
            "This widget configures the LLM\n"
            "for use in the Chat widget.\n\n"
            "Connect a Retriever from the\n"
            "RAG widget (required)."
        )
    
    def _update_model_info(self):
        """Update model information display"""
        model_keys = list(LLM_OPTIONS.keys())
        model_name = model_keys[self.selected_llm]
        config = LLM_OPTIONS[model_name]
        info = f"Type: {config['type']}"
        self.model_info_label.setText(info)
    
    @Inputs.retriever
    def set_retriever(self, retriever):
        """Handle input retriever from RAG widget"""
        self.retriever = retriever
        
        if retriever is None:
            self.rag_status_label.setText("⚠ Waiting for retriever...")
            self.info.set_input_summary(self.info.NoInput)
        else:
            self.rag_status_label.setText("✓ Retriever connected")
            self.info.set_input_summary("Retriever connected")
        
        self._update_config()
    
    def _update_config(self):
        """Update and send LLM configuration"""
        model_keys = list(LLM_OPTIONS.keys())
        model_name = model_keys[self.selected_llm]
        model_config = LLM_OPTIONS[model_name]
        
        # Only send config if retriever is connected
        if self.retriever is None:
            self.Outputs.llm_config.send(None)
            self.info.set_output_summary(self.info.NoOutput)
            return
        
        self.llm_config = {
            "model_name": model_name,
            "model_type": model_config["type"],
            "model": model_config["model"],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "streaming": self.streaming,
            "retriever": self.retriever,
            "rag_enabled": True
        }
        
        self._update_model_info()
        self.Outputs.llm_config.send(self.llm_config)
        
        # Update output summary
        status = f"{model_name} with RAG"
        self.info.set_output_summary(status)


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview
    WidgetPreview(OWLLM).run()
