import re
import random

def _process_spintax(html: str) -> str:
    """Implement nested Spintax '{Hi|Hello}' replacement."""
    pattern = re.compile(r'\{([^{}]*\|[^{}]*)\}')

    while True:
        match_count = 0
        def replacer(match):
            nonlocal match_count
            match_count += 1
            options = match.group(1).split('|')
            return random.choice(options)
            
        html = pattern.sub(replacer, html)
        if match_count == 0:
            break
            
    return html

print(_process_spintax("Hello {World|Universe}, how are {you|we}?"))
print(_process_spintax("CSS { margin: 0; padding: 0; }"))
print(_process_spintax("Spintax with 3: {A|B|C}"))
print(_process_spintax("Nested: {Hi {John|Jane}|Hello {Bob|Alice}}!"))
