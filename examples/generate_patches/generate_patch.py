import os
import logging
import datetime
import tempfile
import subprocess
from typing import Dict, List

from graph_of_thoughts import controller, language_models, prompter, parser
from graph_of_thoughts.operations import (
    Operation, OperationType, Thought, Generate, Aggregate, GraphOfOperations, Score, KeepBestN
)
from graph_of_thoughts.language_models import AbstractLanguageModel
from graph_of_thoughts.prompter import Prompter
from graph_of_thoughts.parser import Parser

class PatchPrompter(prompter.Prompter):
    """
    Prompter for generating, improving, and aggregating code patches.
    """

    generate_patch_prompt = """<Instruction>
    You are an expert software engineer specializing in security.
    Based on the provided root cause analysis and the vulnerable code, rewrite the entire code to fix the vulnerability.

    **VERY IMPORTANT RULES:**
    1.  You MUST output the COMPLETE, modified Java code for the file.
    2.  The code must be syntactically correct and compilable.
    3.  Do NOT output a `diff` or a patch. Output the entire file content.

    Output ONLY the code content within <PatchedCode> and </PatchedCode> tags.
    </Instruction>
    <Root Cause Analysis>{root_cause}</Root Cause Analysis>
    <Vulnerable Code>
    ```java
    {vulnerable_code}
    ```
    </Vulnerable Code>
    <PatchedCode>
    """

    improve_patch_prompt = """<Instruction>
You are an expert software engineer. Your previously generated code failed to compile.
Analyze the original vulnerable code, your faulty code, and the Java compiler error. Then, rewrite the entire code to fix the compilation error and the original vulnerability.

**VERY IMPORTANT RULES:**
1.  You MUST output the COMPLETE, fixed Java code for the file.
2.  The code must be syntactically correct and compilable.
3.  Do NOT output a `diff` or a patch. Output the entire file content.

Output ONLY the new code content within <PatchedCode> and </PatchedCode> tags.
</Instruction>
<Vulnerable Code>
```java
{vulnerable_code}
```
</Vulnerable Code>
<Faulty Code>
```java
{patched_code}
```
</Faulty Code>
<Compiler Error Log>
{error}
</Compiler Error Log>
<PatchedCode>
"""

    aggregate_patches_prompt = """<Instruction>
You are a master software architect. You have been provided with several candidate solutions, all of which are compilable.
Your task is to analyze each solution and synthesize them into a single, superior final version of the code that incorporates the best ideas from all candidates.
The final output must be the complete, final Java code.
Output the final, synthesized code within <FinalCode> and </FinalCode> tags.
</Instruction>
<Root Cause Analysis>{root_cause}</Root Cause Analysis>
<Vulnerable Code>
```java
{vulnerable_code}
```
</Vulnerable Code>
<Validated Candidate Solutions>
{patches}
</Validated Candidate Solutions>
<FinalCode>
"""

    _score_prompt_template = """<Instruction>
You are a senior software engineer and security expert.
Your task is to evaluate a generated code solution based on the original vulnerability and code.
Provide a score from 1 to 10 based on the following criteria:
1.  **Vulnerability Fix (Weight: 40%)**: Does the new code correctly and completely fix the described vulnerability?
2.  **Correctness (Weight: 35%)**: Is the code syntactically correct and free of obvious bugs? Does it preserve the original functionality?
3.  **Code Quality (Weight: 15%)**: Is the code clean, well-structured, and maintainable?
4.  **Simplicity (Weight: 10%)**: Is the code simple and easy to understand?
Output your evaluation in a JSON object with two keys: "score" (the calculated integer score) and "rationale" (a brief explanation for your score).
</Instruction>
<Root Cause Analysis>{root_cause}</Root Cause Analysis>
<Vulnerable Code>
```java
{vulnerable_code}
```
</Vulnerable Code>
<Generated Code>
```java
{patched_code}
```
</Generated Code>
<Evaluation>
"""

    def generate_prompt(self, num_branches: int, **kwargs) -> str:
        return self.generate_patch_prompt.format(**kwargs)

    def improve_prompt(self, **kwargs) -> str:
        return self.improve_patch_prompt.format(**kwargs)

    def aggregation_prompt(self, state_dicts: List[Dict], **kwargs) -> str:
        state = state_dicts[0]
        patches_str = ""
        for i, d in enumerate(state_dicts):
            patches_str += f"--- Candidate Solution {i+1} ---\n```java\n{d['patched_code']}\n```\n\n"
        
        return self.aggregate_patches_prompt.format(
            root_cause=state['root_cause'],
            vulnerable_code=state['vulnerable_code'],
            patches=patches_str.strip()
        )

    def validation_prompt(self, **kwargs) -> str: pass
    
    def score_prompt(self, state_dicts: List[Dict], **kwargs) -> str:
        # Assuming we score one thought at a time for this implementation
        state = state_dicts[0]
        return self._score_prompt_template.format(
            root_cause=state['root_cause'],
            vulnerable_code=state['vulnerable_code'],
            patched_code=state['patched_code']
        )


class PatchParser(parser.Parser):
    def strip_answer_helper(self, text: str, tag: str) -> str:
        try:
            content = ""
            start_tag = f"<{tag}>"
            end_tag = f"</{tag}>"
            
            # Try to find content within tags first
            start_idx = text.find(start_tag)
            if start_idx != -1:
                start_idx += len(start_tag)
                end_idx = text.find(end_tag, start_idx)
                if end_idx != -1:
                    content = text[start_idx:end_idx]

            # If no content found via tags, check for markdown blocks
            if not content.strip():
                if '```java' in text:
                    # Extract content between ```java and ```
                    content = text.split('```java')[1].split('```')[0]
                elif '```' in text:
                    # A more robust split to handle multiple blocks
                    parts = text.split('```')
                    if len(parts) > 1:
                        # Assume the first block is the one we want
                        content = parts[1]
                        # It might have 'java' as the first line
                        if content.lower().strip().startswith('java'):
                            content = content.strip()[4:]

            return content.strip()
        except Exception:
            return ""

    def parse_generate_answer(self, state: Dict, texts: List[str]) -> List[Dict]:
        new_states = []
        for text in texts:
            patched_code = self.strip_answer_helper(text, "PatchedCode")
            if patched_code:
                new_state = state.copy()
                new_state['patched_code'] = patched_code
                new_states.append(new_state)
        return new_states
    
    def parse_improve_answer(self, state: Dict, texts: List[str]) -> Dict:
        patched_code = self.strip_answer_helper(texts[0], "PatchedCode")
        if patched_code:
            new_state = state.copy()
            new_state['patched_code'] = patched_code
            return new_state
        return state

    def parse_aggregation_answer(self, original_states: List[Dict], texts: List[str]) -> List[Dict]:
        final_code = self.strip_answer_helper(texts[0], "FinalCode")
        if final_code:
            new_state = original_states[0].copy()
            new_state['final_code'] = final_code
            return [new_state]
        return []

    def parse_validation_answer(self, state: Dict, texts: List[str]) -> bool: return False
    
    def parse_score_answer(self, states: List[Dict], texts: List[str]) -> List[float]:
        scores = []
        for i, text in enumerate(texts):
            try:
                # Extract the JSON part from the response
                json_text = self.strip_answer_helper(text, "Evaluation")
                if not json_text:
                    # Fallback for raw JSON in response
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    if start != -1 and end != -1:
                        json_text = text[start:end]

                parsed = json.loads(json_text)
                score = float(parsed.get("score", 0.0))
                rationale = parsed.get("rationale", "")
                
                # Update the corresponding state with the rationale
                if i < len(states):
                    states[i]['score'] = score
                    states[i]['rationale'] = rationale
                
                scores.append(score)

            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logging.error(f"Failed to parse score: {e}\nResponse was: {text}")
                # Append a low score to penalize parsing failures
                if i < len(states):
                    states[i]['rationale'] = f"Failed to parse score from LLM response: {text}"
                scores.append(0.0)
        return scores


# THIS OPERATION IS NO LONGER USED, replaced by Score operation from the framework
class ValidateAndImproveOperation(Operation):
    """
    Custom operation to validate a generated Java code by compiling it.
    If it fails, it feeds the error back to the LLM to generate an improved version.
    THIS OPERATION IS CURRENTLY DISABLED BY USER REQUEST.
    """
    def __init__(self, prompter: prompter.Prompter, vulnerable_file_name: str, num_tries: int = 3):
        super().__init__()
        self.operation_type = OperationType.validate_and_improve
        self.prompter = prompter
        self.vulnerable_file_name = vulnerable_file_name
        self.num_tries = num_tries
        self.thoughts: List[Thought] = []

    def _execute(self, lm: AbstractLanguageModel, prompter: Prompter, parser: Parser, **kwargs) -> None:
        # USER REQUEST: Skip compilation. Treat all generated thoughts as valid.
        valid_thoughts = []
        for thought in self.get_previous_thoughts():
            logging.info("Skipping validation and improvement as per user request.")
            thought.valid = True
            valid_thoughts.append(thought)
        self.thoughts = valid_thoughts

    def get_thoughts(self) -> List[Thought]:
        return self.thoughts



def advanced_patch_graph_with_aggregation(patch_prompter, patch_parser) -> GraphOfOperations:
    """
    Defines the graph of operations for generating, scoring, and aggregating patches
    to better reflect GoT's refining capabilities.
    """
    # Step 1: Generate multiple candidate patches
    op1_generate = Generate(num_branches_prompt=5) # Example: Generate 5 candidate patches initially

    # Step 2: Score each candidate individually
    op2_score = Score(combined_scoring=False)

    # Step 3: Keep the top N best candidates (e.g., top 3) for aggregation
    #         Instead of n=1, we keep multiple candidates to aggregate their insights.
    op3_keep_best_n = KeepBestN(n=3) # Keep multiple for aggregation

    # Step 4: Aggregate the insights from the kept best N candidates
    #         This is the 'refining' step where different thoughts are combined.
    #         The 'aggregation_prompt' in PatchPrompter will be used here.
    op4_aggregate = Aggregate()

    # Step 5: (Optional) Score the aggregated patch
    #         It's good practice to evaluate the final aggregated solution.
    op5_score_final = Score(combined_scoring=False) # Score the single aggregated patch

    # Define the graph flow
    graph = GraphOfOperations()
    graph.add_operation(op1_generate)
    graph.add_operation(op2_score)
    graph.add_operation(op3_keep_best_n)
    graph.add_operation(op4_aggregate)
    graph.add_operation(op5_score_final) # Optional, but recommended for final evaluation

    # Connect the operations
    op1_generate.add_successor(op2_score)        # Generate -> Score
    op2_score.add_successor(op3_keep_best_n)     # Score -> Keep Best N
    op3_keep_best_n.add_successor(op4_aggregate) # Keep Best N -> Aggregate (multiple inputs to aggregate)
    op4_aggregate.add_successor(op5_score_final) # Aggregate -> Score Final (single aggregated output)

    return graph
def run(lm_name: str):
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(filename).1s:%(lineno)d] - %(message)s') # [cite: 1, 1]

    script_dir = os.path.dirname(__file__)
    try:
        with open(os.path.join(script_dir, "vulnerable.java"), "r") as f:
            vulnerable_code = f.read()
        with open(os.path.join(script_dir, "root_cause.txt"), "r") as f:
            root_cause = f.read()
    except FileNotFoundError as e:
        logging.error(f"Input file not found: {e}")
        return

    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "graph_of_thoughts", "language_models", "config.json")
        lm = language_models.ChatGPT(config_path=config_path, model_name=lm_name)
    except Exception as e:
        logging.error(f"LM initialization error: {e}")
        return

    patch_prompter = PatchPrompter()
    patch_parser = PatchParser()
    # 변경된 그래프 사용
    graph = advanced_patch_graph_with_aggregation(patch_prompter, patch_parser)
     
    initial_state = {
        "vulnerable_code": vulnerable_code,
        "root_cause": root_cause,
    }
    
    ctrl = controller.Controller(lm, graph, patch_prompter, patch_parser, initial_state)

    print("Starting Patch Generation with Aggregation and Scoring...")
    start_time = datetime.datetime.now()
    ctrl.run()
    end_time = datetime.datetime.now()
    print(f"Patch generation finished in {end_time - start_time}.")

    # Get the best result from the final scoring operation (op5_score_final, index 4 in graph.operations)
    # The Aggregate operation will produce a single thought, which op5_score_final then scores.
    final_results = graph.operations[4].get_thoughts() # Index 4 corresponds to op5_score_final
    if final_results:
        best_thought = final_results[0] # There should only be one aggregated thought
        final_code = best_thought.state.get('final_code', 'Final code not found.') # Aggregation output is 'final_code'
        score = best_thought.state.get('score', 'N/A')
        rationale = best_thought.state.get('rationale', 'N/A')

        print("\n" + "="*50)
        print(f"Final Aggregated Code (Score: {score})")
        print("="*50)
        print(f"Rationale: {rationale}")
        print("-" * 50)
        print(final_code)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Ensure the filename reflects aggregation
        file_path = os.path.join(script_dir, f"generated_aggregated_patch_{timestamp}.java")
        with open(file_path, "w") as f:
            f.write(f"// Score: {score}\n// Rationale: {rationale}\n\n{final_code}")
        print(f"\nFinal code saved to {file_path}")
    else:
        print("\nNo code was generated or survived the aggregation/scoring process.")

if __name__ == "__main__":
    import json
    run(lm_name="chatgpt")