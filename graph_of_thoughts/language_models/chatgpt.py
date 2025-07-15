# Copyright (c) 2023 ETH Zurich.
#                    All rights reserved.
#
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# main author: Nils Blach

import backoff
import os
import random
import time
import json
import tempfile
import logging
import openai
from typing import List, Dict, Union
from openai import OpenAI, OpenAIError
from openai.types.chat.chat_completion import ChatCompletion

from .abstract_language_model import AbstractLanguageModel


class ChatGPT(AbstractLanguageModel):
    """
    The ChatGPT class handles interactions with the OpenAI models using the provided configuration.

    Inherits from the AbstractLanguageModel and implements its abstract methods.
    """

    def __init__(
        self,
        config_path: str = "",
        model_name: str = "chatgpt",
        cache: bool = False,
        logger: logging.Logger = None,
    ) -> None:
        """
        Initialize the ChatGPT instance with configuration, model details, and caching options.

        :param config_path: Path to the configuration file. Defaults to "".
        :type config_path: str
        :param model_name: Name of the model, default is 'chatgpt'. Used to select the correct configuration.
        :type model_name: str
        :param cache: Flag to determine whether to cache responses. Defaults to False.
        :type cache: bool
        """
        super().__init__(config_path, model_name, cache, logger)
        self.config: Dict = self.config[model_name]
        # The model_id is the id of the model that is used for chatgpt, i.e. gpt-4, gpt-3.5-turbo, etc.
        self.model_id: str = self.config["model_id"]
        # The prompt_token_cost and response_token_cost are the costs for 1000 prompt tokens and 1000 response tokens respectively.
        self.prompt_token_cost: float = self.config["prompt_token_cost"]
        self.response_token_cost: float = self.config["response_token_cost"]
        # The temperature of a model is defined as the randomness of the model's output.
        self.temperature: float = self.config["temperature"]
        # The maximum number of tokens to generate in the chat completion.
        self.max_tokens: int = self.config["max_tokens"]
        # The stop sequence is a sequence of tokens that the model will stop generating at (it will not generate the stop sequence).
        self.stop: Union[str, List[str], None] = self.config["stop"]
        # The account organization is the organization that is used for chatgpt.
        self.organization: str = self.config["organization"]
        self.api_key: str = self.config["api_key"]

        if not self.api_key:
            self.api_key = os.getenv("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Please set it in the config file or as an environment variable OPENAI_API_KEY."
            )

        if self.organization:
            openai.organization = self.organization
        openai.api_key = self.api_key
        
        # Initialize the OpenAI Client
        self.client = openai.OpenAI(api_key=self.api_key, organization=self.organization)

    def generate(self, prompt: str, num_generations: int) -> List[str]:
        """
        Generates `num_generations` responses for the given prompt.
        """
        response = self.query(prompt, num_responses=num_generations)
        return self.get_response_texts(response)

    def generate_text(self, prompt: str, num_branches: int) -> List[str]:
        """
        Generates `num_branches` responses for the given prompt.
        A convenience method that wraps the generate method.
        """
        return self.generate(prompt, num_branches)

    @classmethod
    def from_config(cls, config_path: str, config_key: str = "chatgpt", logger: logging.Logger = None) -> "ChatGPT":
        """
        Creates an instance of the ChatGPT language model from a configuration file.
        """
        try:
            with open(config_path, "r") as f:
                full_config = json.load(f)
            model_config = full_config[config_key]
            
            # This is a bit of a workaround to match the expected __init__ structure
            # of the original ChatGPT class, which expects a different config format.
            
            # Create a temporary config structure that the old __init__ can understand
            temp_init_config = {
                config_key: {
                    "model_id": model_config.get("model_name", "gpt-4-0613"),
                    "prompt_token_cost": model_config.get("prompt_token_cost", 0.03),
                    "response_token_cost": model_config.get("response_token_cost", 0.06),
                    "temperature": model_config.get("temperature", 1.0),
                    "max_tokens": model_config.get("max_tokens", 4096),
                    "stop": model_config.get("stop"),
                    "organization": model_config.get("organization"),
                    "api_key": model_config.get("api_key")
                }
            }
            
            # Create a temporary config file to pass to the constructor
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as temp_f:
                json.dump(temp_init_config, temp_f)
                temp_path = temp_f.name

            instance = cls(config_path=temp_path, model_name=config_key, logger=logger)
            
            # Clean up the temporary file
            os.remove(temp_path)
            
            return instance

        except (FileNotFoundError, KeyError) as e:
            logging.error(f"Failed to load config for {config_key}: {e}")
            raise

    def query(
        self, query: str, num_responses: int = 1
    ) -> Union[List[ChatCompletion], ChatCompletion]:
        """
        Query the OpenAI model for responses.

        :param query: The query to be posed to the language model.
        :type query: str
        :param num_responses: Number of desired responses, default is 1.
        :type num_responses: int
        :return: Response(s) from the OpenAI model.
        :rtype: Dict
        """
        if self.cache and query in self.response_cache:
            return self.response_cache[query]

        if self.llm_logger:
            self.llm_logger.info(f"--- REQUEST ---\n{query}\n")

        if num_responses == 1:
            response = self.chat([{"role": "user", "content": query}], num_responses)
        else:
            response = []
            next_try = num_responses
            total_num_attempts = num_responses
            while num_responses > 0 and total_num_attempts > 0:
                try:
                    assert next_try > 0
                    res = self.chat([{"role": "user", "content": query}], next_try)
                    response.append(res)
                    num_responses -= next_try
                    next_try = min(num_responses, next_try)
                except Exception as e:
                    next_try = (next_try + 1) // 2
                    self.logger.warning(
                        f"Error in chatgpt: {e}, trying again with {next_try} samples"
                    )
                    time.sleep(random.randint(1, 3))
                    total_num_attempts -= 1

        if self.llm_logger:
            # Note: This might not be perfect if response is a list of completions
            if isinstance(response, list):
                all_choices = []
                for r in response:
                    all_choices.extend(r.choices)
                response_text = "\n".join([choice.message.content for choice in all_choices])
            else:
                response_text = "\n".join([choice.message.content for choice in response.choices])
            self.llm_logger.info(f"--- RESPONSE ---\n{response_text}\n")

        if self.cache:
            self.response_cache[query] = response
        return response

    @backoff.on_exception(backoff.expo, OpenAIError, max_time=10, max_tries=6)
    def chat(self, messages: List[Dict], num_responses: int = 1) -> ChatCompletion:
        """
        Send chat messages to the OpenAI model and retrieves the model's response.
        Implements backoff on OpenAI error.

        :param messages: A list of message dictionaries for the chat.
        :type messages: List[Dict]
        :param num_responses: Number of desired responses, default is 1.
        :type num_responses: int
        :return: The OpenAI model's response.
        :rtype: ChatCompletion
        """
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            n=num_responses,
            stop=self.stop,
        )

        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens
        prompt_tokens_k = float(self.prompt_tokens) / 1000.0
        completion_tokens_k = float(self.completion_tokens) / 1000.0
        self.cost = (
            self.prompt_token_cost * prompt_tokens_k
            + self.response_token_cost * completion_tokens_k
        )
        self.logger.info(
            f"This is the response from chatgpt: {response}"
            f"\nThis is the cost of the response: {self.cost}"
        )
        return response

    def get_response_texts(
        self, query_response: Union[List[ChatCompletion], ChatCompletion]
    ) -> List[str]:
        """
        Extract the response texts from the query response.

        :param query_response: The response dictionary (or list of dictionaries) from the OpenAI model.
        :type query_response: Union[List[ChatCompletion], ChatCompletion]
        :return: List of response strings.
        :rtype: List[str]
        """
        if not isinstance(query_response, List):
            query_response = [query_response]
        return [
            choice.message.content
            for response in query_response
            for choice in response.choices
        ]
