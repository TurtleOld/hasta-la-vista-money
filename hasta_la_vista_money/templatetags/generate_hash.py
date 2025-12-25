import hashlib
import random
import string

from django import template

register = template.Library()

system_random = random.SystemRandom()


@register.simple_tag()
def word_hash() -> str:
    """Generate hash from random letter combinations.

    Returns:
        SHA256 hash of random ASCII letters string.
    """
    letters = string.ascii_letters
    random_string = ''.join(
        system_random.choice(letters) for _ in range(len(letters))
    )
    byte_word = bytes(random_string, encoding='utf-8')
    return str(hashlib.sha256(byte_word).hexdigest())
