import logging
from litellm import cost_per_token

logger = logging.getLogger(__name__)

def calculate_event_cost(model_name: str, usage_metadata) -> float:
    if not usage_metadata:
        return 0.0
    
    prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
    completion_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
    
    if prompt_tokens == 0 and completion_tokens == 0:
        return 0.0
        
    try:
        # Some models in Litellm might expect "gemini/" prefix, etc.
        # We handle known prefixes if not present or handle gracefully.
        cost, _ = cost_per_token(model=model_name, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return cost
    except Exception as e:
        logger.warning(f"Failed to calculate cost for model {model_name}: {e}")
        return 0.0
