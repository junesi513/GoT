import os
import logging
import datetime
from typing import Dict, List

from graph_of_thoughts import controller, language_models, operations, prompter, parser

class PatchPrompter(prompter.Prompter):
    """
    Prompter for generating and evaluating code patches.
    """

    # 1. 패치 생성 프롬프트
    generate_patch_prompt = """<Instruction>
You are an expert software engineer specializing in security.
Based on the provided root cause analysis and the vulnerable code, generate a patch to fix the vulnerability.
The patch must be in the standard `diff` format.
Output ONLY the patch content within <Patch> and </Patch> tags.
</Instruction>

<Root Cause Analysis>
{root_cause}
</Root Cause Analysis>

<Vulnerable Code>
```java
{vulnerable_code}
```
</Vulnerable Code>

<Patch>
"""

    # 2. 패치 평가 프롬프트 (Evaluator LLM용)
    score_patch_prompt = """<Instruction>
You are an expert code reviewer and security auditor.
Your task is to score the provided patch on a scale of 1 to 10 based on the following criteria:
- **Correctness (30%)**: Does the patch correctly fix the identified root cause? Does it compile and maintain the original functionality?
- **Change (30%)**: Is the patch a minimal change?
- **Security (15%)**: Does the patch introduce any new vulnerabilities? Is it a robust security fix?
- **Similarity (15%)**: Is the patch similar to the vulnerable code?
- **Clarity (10%)**: Is the patch easy to understand and well-formatted?

A score of 10 means the patch is perfect. A score of 1 means it's completely wrong.
Analyze the patch's effectiveness and provide a final score.
Output ONLY a single integer score within <Score> and </Score> tags.
</Instruction>

<Root Cause Analysis>
{root_cause}
</Root Cause Analysis>

<Vulnerable Code>
```java
{vulnerable_code}
```
</Vulnerable Code>

<Patch to Score>
```diff
{patch}
```
</Patch to Score>

<Score>
"""

    def generate_prompt(self, num_branches: int, **kwargs) -> str:
        return self.generate_patch_prompt.format(
            root_cause=kwargs['root_cause'],
            vulnerable_code=kwargs['vulnerable_code']
        )

    def score_prompt(self, state_dicts: List[Dict], **kwargs) -> str:
        state = state_dicts[0]
        return self.score_patch_prompt.format(
            root_cause=state['root_cause'],
            vulnerable_code=state['vulnerable_code'],
            patch=state['patch']
        )

    # 사용하지 않는 추상 메서드
    def aggregation_prompt(self, state_dicts: List[Dict], **kwargs) -> str: pass
    def improve_prompt(self, **kwargs) -> str: pass
    def validation_prompt(self, **kwargs) -> str: pass


class PatchParser(parser.Parser):
    """
    Parser for extracting patches and scores from LLM responses.
    """
    def strip_answer_helper(self, text: str, tag: str) -> str:
        try:
            start_tag = f"<{tag}>"
            end_tag = f"</{tag}>"
            start_index = text.find(start_tag) + len(start_tag)
            end_index = text.find(end_tag)
            return text[start_index:end_index].strip()
        except Exception:
            return ""

    def parse_generate_answer(self, state: Dict, texts: List[str]) -> List[Dict]:
        new_states = []
        for text in texts:
            patch = self.strip_answer_helper(text, "Patch")
            if patch:
                new_state = state.copy()
                new_state['patch'] = patch
                new_states.append(new_state)
        return new_states

    def parse_score_answer(self, states: List[Dict], texts: List[str]) -> List[float]:
        scores = []
        for text in texts:
            try:
                score_str = self.strip_answer_helper(text, "Score")
                scores.append(float(score_str))
            except (ValueError, IndexError):
                scores.append(0.0)
        return scores

    # 사용하지 않는 추상 메서드
    def parse_aggregation_answer(self, original_states: List[Dict], texts: List[str]) -> List[Dict]: pass
    def parse_improve_answer(self, state: Dict, texts: List[str]) -> Dict: pass
    def parse_validation_answer(self, state: Dict, texts: List[str]) -> bool: pass


def patch_generation_graph() -> operations.GraphOfOperations:
    """
    Defines the GoT graph for generating and evaluating patches.
    Flow: Generate(n=3) -> Score -> KeepBestN(n=1)
    """
    op1 = operations.Generate(num_branches_prompt=3)
    op2 = operations.Score()
    op3 = operations.KeepBestN(1)

    graph = operations.GraphOfOperations()
    graph.add_operation(op1)
    graph.add_operation(op2)
    graph.add_operation(op3)
    
    op1.add_successor(op2)
    op2.add_successor(op3)
    
    return graph

def run(lm_name: str, evaluator_lm_name: str):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    
    # 입력 파일 읽기
    script_dir = os.path.dirname(__file__)
    try:
        with open(os.path.join(script_dir, "vulnerable.java"), "r") as f:
            vulnerable_code = f.read()
        with open(os.path.join(script_dir, "root_cause.txt"), "r") as f:
            root_cause = f.read()
    except FileNotFoundError as e:
        logging.error(f"Input file not found: {e}")
        return

    # 언어 모델 설정
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "graph_of_thoughts", "language_models", "config.json")
        generator_lm = language_models.ChatGPT(config_path=config_path, model_name=lm_name)
        evaluator_lm = language_models.ChatGPT(config_path=config_path, model_name=evaluator_lm_name)
    except Exception as e:
        logging.error(f"LM initialization error: {e}")
        return

    patch_prompter = PatchPrompter()
    patch_parser = PatchParser()
    graph = patch_generation_graph()

    initial_state = {
        "vulnerable_code": vulnerable_code,
        "root_cause": root_cause,
    }
    
    # Controller는 lm, evaluator_lm을 따로 받지 않으므로, Score Operation을 커스터마이징 해야함.
    # 이 예제에서는 단순화를 위해 동일 LLM을 사용하지만, 원래 의도는 분리하는 것.
    # 프레임워크의 Score Operation은 Controller의 lm을 그대로 사용하므로,
    # evaluator_lm을 사용하려면 Score Operation을 상속받는 새로운 Operation을 만들어야 함.
    # 우선은 동일 LM으로 진행.
    ctrl = controller.Controller(generator_lm, graph, patch_prompter, patch_parser, initial_state)

    print("Starting Patch Generation with GoT...")
    start_time = datetime.datetime.now()
    ctrl.run()
    end_time = datetime.datetime.now()
    print(f"Patch generation finished in {end_time - start_time}.")

    final_results = graph.operations[2].get_thoughts()
    if final_results:
        best_patch = final_results[0].state.get('patch', 'Patch not found.')
        score = final_results[0].score
        print("\n" + "="*50)
        print(f"Best Patch (Score: {score})")
        print("="*50)
        print(best_patch)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        patch_path = os.path.join(script_dir, f"generated_patch_{timestamp}.diff")
        with open(patch_path, "w") as f:
            f.write(best_patch)
        print(f"\nPatch saved to {patch_path}")
    else:
        print("\nNo patch was generated.")

if __name__ == "__main__":
    run(lm_name="chatgpt4", evaluator_lm_name="chatgpt4") 