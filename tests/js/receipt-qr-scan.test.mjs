import assert from 'node:assert/strict';
import test from 'node:test';

let scanPageFactory = null;

globalThis.window = {
  Alpine: {
    data(name, factory) {
      if (name === 'receiptQRScanPage') {
        scanPageFactory = factory;
      }
    },
  },
};

await import('../../static/js/pages/receipt-qr-scan.js');

assert.ok(scanPageFactory, 'scanner page was not registered with Alpine');

const originalFetch = globalThis.fetch;

function createPage() {
  const page = scanPageFactory();
  page.$el = {
    dataset: { notificationsUrl: '/receipts/processing/notifications/' },
  };
  return page;
}

test('first open does not poll notifications before the first scan', async () => {
  const page = createPage();
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('unexpected notification request');
  };

  try {
    await page.pollNotifications();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls, 0);
  assert.equal(page.noticeMessage, '');
});

test('a notification batch is queued and dismissed one item at a time', async () => {
  const page = createPage();
  page.trackedLogIds.add(5);
  globalThis.fetch = async () => ({
    json: async () => ({
      notifications: [
        { id: 1, url: '/receipts/view/1/', message: 'first' },
        { id: 2, url: '/receipts/view/2/', message: 'second' },
      ],
    }),
  });

  try {
    await page.pollNotifications();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(page.noticeMessage, 'first');
  assert.equal(page.noticeLink, '/receipts/view/1/');
  page.dismissNotice();
  assert.equal(page.noticeMessage, 'second');
  assert.equal(page.noticeLink, '/receipts/view/2/');
  page.dismissNotice();
  assert.equal(page.noticeMessage, '');
  assert.equal(page.noticeLink, '');
});

test('duplicate scan does not increase the sent counter', async () => {
  const page = createPage();
  page.messages = { submitFailed: 'failed' };
  page.$el.dataset.scanUrl = '/receipts/scan-qr/';
  page.$refs = {
    scanForm: {
      querySelector(selector) {
        if (selector === '[name="csrfmiddlewaretoken"]') {
          return { value: 'token' };
        }
        if (selector === '[name="account"]') {
          return { value: '1' };
        }
        throw new Error(`unexpected selector ${selector}`);
      },
    },
  };
  let pollCalls = 0;
  page.pollNotifications = () => {
    pollCalls += 1;
  };

  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      status: 'duplicate',
      message: 'duplicate',
      url: '/receipts/view/1/',
    }),
  });
  const duplicate = await page.sendQR('duplicate-qr');
  assert.equal(duplicate.status, 'duplicate');
  assert.equal(page.sentCount, 0);
  assert.equal(pollCalls, 0);

  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      status: 'queued',
      message: 'queued',
      log_id: 42,
    }),
  });
  try {
    const queued = await page.sendQR('new-qr');
    assert.equal(queued.status, 'queued');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(page.sentCount, 1);
  assert.equal(pollCalls, 1);
  assert.equal(page.trackedLogIds.has(42), true);
});
