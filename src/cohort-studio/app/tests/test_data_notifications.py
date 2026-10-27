from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_opt_in_and_background_data_ready_notification(page, app_url):
    page.add_init_script('''
      window.sentNotifications = [];
      Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
      window.Notification = class {
        static permission = 'granted';
        static async requestPermission() { return 'granted'; }
        constructor(title, options) { window.sentNotifications.push({title, ...options}); }
        close() {}
      };
    ''')
    page.goto(app_url)
    page.get_by_text('Settings', exact=True).first.click()
    toggle = page.get_by_label('Notify when data is ready')
    toggle.check()
    expect(toggle).to_be_checked()
    assert page.evaluate("localStorage.getItem('cohort-studio-notifications')") == 'on'
    page.evaluate('''() => {
      sessionStorage.setItem('studio-data-jobs', JSON.stringify(['notify-test']));
    }''')
    page.route('**/api/data-jobs/notify-test', lambda route: route.fulfill(json={
        'job_id': 'notify-test', 'kind': 'join', 'status': 'complete',
    }))
    page.reload()
    page.wait_for_function("window.sentNotifications.length === 1")
    assert page.evaluate('window.sentNotifications[0].title') == 'Join is ready'
    page.wait_for_timeout(2200)
    assert page.evaluate('window.sentNotifications.length') == 1
