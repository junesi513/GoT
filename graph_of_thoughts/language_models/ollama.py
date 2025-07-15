import os
import json
import logging
from typing import Dict, List, Any

try:
    import requests
except ImportError:
    raise ImportError("requests is not installed. Please install it with `pip install requests`")

from .abstract_language_model import AbstractLanguageModel

class OllamaLanguageModel(AbstractLanguageModel):
    """
    Language model for interacting with a local Ollama server.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the OllamaLanguageModel.
        Expects a configuration dictionary with 'model_name' and optional 'server_url'.
        """
        super().__init__(config)
        self.model_name = self.config.get("model_name", "qwen:32b") # Default to qwen32
        self.server_url = self.config.get("server_url", "http://localhost:11434")
        self.api_endpoint = f"{self.server_url}/api/generate"
        
        logging.info(f"Ollama model initialized with model '{self.model_name}' on server {self.server_url}")
        self._check_server_connection()

    def _check_server_connection(self):
        try:
            response = requests.get(self.server_url, timeout=5)
            response.raise_for_status()
            logging.info("Successfully connected to Ollama server.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Could not connect to Ollama server at {self.server_url}. Please ensure it's running.")
            raise ConnectionError(f"Ollama server not reachable: {e}")


    def _query_lm(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        stop=None,
    ) -> Dict[str, Any]:
        """
        Queries the local Ollama model.
        """
        responses = []
        for _ in range(n):
            try:
                payload = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                        "stop": stop if stop else [],
                    }
                }
                response = requests.post(self.api_endpoint, json=payload, timeout=300)
                response.raise_for_status()
                response_json = response.json()
                responses.append(response_json.get("response", ""))
            except requests.exceptions.RequestException as e:
                logging.error(f"Error querying Ollama: {e}")
                responses.append("")

        # Mimic the OpenAI response structure
        return {
            "choices": [
                {"message": {"content": text}} for text in responses
            ]
        }

    @classmethod
    def from_config(cls, config_path: str, config_key="ollama") -> "OllamaLanguageModel":
        """
        Creates an instance of the language model from a configuration file.
        """
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            model_config = config[config_key]
            logging.debug(f"Loaded config from {config_path} for {config_key}")
            return cls(model_config)
        except (FileNotFoundError, KeyError) as e:
            logging.error(f"Failed to load config for {config_key}: {e}")
            raise 