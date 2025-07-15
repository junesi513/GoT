import os
import json
import logging
from typing import Dict, List, Any

try:
    import google.generativeai as genai
except ImportError:
    raise ImportError(
        "Google Generative AI is not installed. Please install it with `pip install google-generativeai`"
    )

from .abstract_language_model import AbstractLanguageModel

class GeminiLanguageModel(AbstractLanguageModel):
    """
    Language model for interacting with Google's Gemini models.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the GeminiLanguageModel.
        Expects a configuration dictionary with 'api_key' and 'model_name'.
        """
        super().__init__(config)
        self.api_key = self.config.get("api_key")
        self.model_name = self.config.get("model_name", "gemini-1.5-pro-latest")

        if not self.api_key:
            self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key not found. "
                "Please set it in the config file or as an environment variable GOOGLE_API_KEY."
            )
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        logging.info(f"Gemini model initialized with {self.model_name}")

    def _query_lm(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        stop=None,
    ) -> Dict[str, Any]:
        """
        Queries the Gemini model.
        Note: Gemini API doesn't support n > 1 directly in a single call with temperature.
              We will call it `n` times to get `n` independent samples.
              The `stop` parameter is also not directly supported in the same way.
        """
        responses = []
        for _ in range(n):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        # candidate_count is not the same as n in OpenAI
                        # it produces n candidates but from a single generation process
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                    ),
                )
                responses.append(response.text)
            except Exception as e:
                logging.error(f"Error querying Gemini: {e}")
                responses.append("")

        # Mimic the OpenAI response structure
        return {
            "choices": [
                {"message": {"content": text}} for text in responses
            ]
        }

    @classmethod
    def from_config(cls, config_path: str, config_key="gemini") -> "GeminiLanguageModel":
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