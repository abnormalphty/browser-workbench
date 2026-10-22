import unittest
class AccountInfoTests(unittest.TestCase):
 def parse(self,text,url='https://claude.ai/settings/billing'):
  from runtime.account_info import parse_account_page
  return parse_account_page(url,text)
 def test_current_plan_is_explicit_and_marketing_is_not_a_subscription(self):
  for plan in ['Free','Pro','Max']:
   self.assertEqual(self.parse('Your current plan\n'+plan)['plan'],plan.lower())
  self.assertEqual(self.parse('Upgrade to Pro\nChoose Max\nFree trial')['plan'],'unknown')
  self.assertEqual(self.parse('当前套餐：Pro')['plan'],'pro')
 def test_only_explicit_account_disable_is_blocked(self):
  self.assertEqual(self.parse('Your account has been disabled. Contact support.','https://claude.ai/login')['status'],'blocked')
  self.assertNotEqual(self.parse('If your account has been disabled, contact support.')['status'],'blocked')
  self.assertNotEqual(self.parse('Unable to complete login. Try another browser.','https://claude.ai/login')['status'],'blocked')
 def test_never_interpret_conversation_or_untrusted_origin_as_account_evidence(self):
  for url in ['https://claude.ai/chat/123','https://claude.ai.example/settings/billing','http://claude.ai/settings/billing']:
   self.assertEqual(self.parse('Your current plan\nPro\nYour account has been disabled',url)['plan'],'unknown')
   self.assertEqual(self.parse('Your current plan\nPro\nYour account has been disabled',url)['status'],'unknown')
