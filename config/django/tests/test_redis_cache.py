"""
Tests for Redis cache configuration and functionality.

These tests verify that Redis caching works correctly in production mode
and that cache operations (set, get, delete, TTL) function as expected.
"""

import time

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase


class RedisCacheConfigTest(TestCase):
    """Test Redis cache configuration."""

    def test_debug_mode_uses_locmem_cache(self):
        """Verify that DEBUG mode uses LocMemCache backend."""
        if settings.DEBUG:
            backend = settings.CACHES['default']['BACKEND']
            self.assertEqual(
                backend,
                'django.core.cache.backends.locmem.LocMemCache',
            )

    def test_cache_backend_config(self):
        """Verify cache backend is configured correctly."""
        backend = settings.CACHES['default']['BACKEND']
        self.assertIsNotNone(backend)
        self.assertIn('cache', backend.lower())


class RedisCacheOperationsTest(TestCase):
    """Test basic cache operations."""

    def setUp(self):
        """Clear cache before each test."""
        cache.clear()

    def tearDown(self):
        """Clear cache after each test."""
        cache.clear()

    def test_cache_set_and_get(self):
        """Test basic set and get operations."""
        test_key = 'test_key'
        test_value = 'test_value'

        cache.set(test_key, test_value, 300)

        cached_value = cache.get(test_key)
        self.assertEqual(cached_value, test_value)

    def test_cache_get_nonexistent_key(self):
        """Test getting a non-existent key returns None."""
        result = cache.get('nonexistent_key')
        self.assertIsNone(result)

    def test_cache_get_with_default(self):
        """Test getting with default value."""
        default_value = 'default'
        result = cache.get('nonexistent_key', default_value)
        self.assertEqual(result, default_value)

    def test_cache_delete(self):
        """Test cache deletion."""
        test_key = 'test_key_delete'
        test_value = 'test_value'

        cache.set(test_key, test_value, 300)
        self.assertEqual(cache.get(test_key), test_value)

        cache.delete(test_key)
        self.assertIsNone(cache.get(test_key))

    def test_cache_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        test_key = 'test_key_ttl'
        test_value = 'test_value'
        ttl = 1

        cache.set(test_key, test_value, ttl)
        self.assertEqual(cache.get(test_key), test_value)

        time.sleep(ttl + 0.5)

        self.assertIsNone(cache.get(test_key))

    def test_cache_many_operations(self):
        """Test setting and getting multiple keys at once."""
        test_data = {
            'key1': 'value1',
            'key2': 'value2',
            'key3': 'value3',
        }

        cache.set_many(test_data, 300)

        results = cache.get_many(list(test_data.keys()))
        self.assertEqual(results, test_data)

    def test_cache_complex_data_types(self):
        """Test caching complex data types."""
        test_dict = {
            'nested': {'key': 'value'},
            'list': [1, 2, 3],
            'tuple': (4, 5, 6),
        }

        cache.set('complex_data', test_dict, 300)

        cached_data = cache.get('complex_data')
        self.assertEqual(cached_data, test_dict)

    def test_cache_increment_decrement(self):
        """Test increment and decrement operations."""
        test_key = 'counter'

        cache.set(test_key, 0, 300)

        cache.incr(test_key)
        self.assertEqual(cache.get(test_key), 1)

        cache.incr(test_key, 5)
        self.assertEqual(cache.get(test_key), 6)

        cache.decr(test_key, 2)
        self.assertEqual(cache.get(test_key), 4)


class CacheKeyFormattingTest(TestCase):
    """Test cache key formatting and prefixes."""

    def setUp(self):
        """Clear cache before each test."""
        cache.clear()

    def tearDown(self):
        """Clear cache after each test."""
        cache.clear()

    def test_cache_key_with_user_id(self):
        """Test cache keys with user IDs."""
        user_id = 123
        cache_key = f'user_stats_{user_id}'
        test_value = {'data': 'test'}

        cache.set(cache_key, test_value, 300)

        result = cache.get(cache_key)
        self.assertEqual(result, test_value)

    def test_cache_key_with_category_type(self):
        """Test cache keys for category trees."""
        user_id = 456
        category_type = 'expense'
        depth = 3
        cache_key = f'category_tree_{category_type}_{user_id}_{depth}'
        test_value = [{'id': 1, 'name': 'Test'}]

        cache.set(cache_key, test_value, 300)

        result = cache.get(cache_key)
        self.assertEqual(result, test_value)

    def test_cache_key_with_group_id(self):
        """Test cache keys for user accounts with groups."""
        user_id = 789
        group_id = 'my'
        cache_key = f'user_accounts_{user_id}_{group_id}'
        test_value = []

        cache.set(cache_key, test_value, 300)

        result = cache.get(cache_key)
        self.assertEqual(result, test_value)
