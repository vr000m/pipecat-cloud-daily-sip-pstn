#!/usr/bin/env node

/**
 * Test script for SIP URI normalization
 * This tests various SIP URI formats to ensure they normalize correctly
 */

// SIP URI normalization function (copy from dial.js)
const normalizeSipUri = (sipUri) => {
  if (!sipUri) return null;
  
  let normalized = sipUri;
  
  // Remove sip: prefix if present (case-insensitive)
  if (normalized.toLowerCase().startsWith('sip:')) {
    normalized = normalized.substring(4);
  }
  
  // Remove port number (e.g., :5060)
  normalized = normalized.replace(/:\d+/, '');
  
  // Remove query parameters (everything after ?)
  const queryIndex = normalized.indexOf('?');
  if (queryIndex !== -1) {
    normalized = normalized.substring(0, queryIndex);
  }
  
  // Remove URI parameters (everything after ;)
  const paramIndex = normalized.indexOf(';');
  if (paramIndex !== -1) {
    normalized = normalized.substring(0, paramIndex);
  }
  
  // Convert to lowercase for case-insensitive comparison
  normalized = normalized.toLowerCase().trim();
  
  return normalized;
};

// Test cases
const testCases = [
  {
    input: 'bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com',
    expected: 'bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com'
  },
  {
    input: 'sip:bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com',
    expected: 'bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com'
  },
  {
    input: 'sip:bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com:5060',
    expected: 'bbc51b7b8b084ebe-stage--1745262134338@daily-bbc51b7b8b084ebe-stage-pinless-sip.dapp.signalwire.com'
  },
  {
    input: 'sip:foobar@dash-sip.dapp.signalwire.com:5060?x-header=2&x-hdr-2=23',
    expected: 'foobar@dash-sip.dapp.signalwire.com'
  },
  {
    input: 'sip:user@domain.com;transport=tcp',
    expected: 'user@domain.com'
  },
  {
    input: 'SIP:USER@DOMAIN.COM',
    expected: 'user@domain.com'
  },
  {
    input: 'user@domain.com:5061?custom=param&another=value',
    expected: 'user@domain.com'
  },
  {
    input: 'sip:test@example.com:5060;transport=udp?header=value',
    expected: 'test@example.com'
  }
];

console.log('Testing SIP URI Normalization\n');
console.log('=' .repeat(80));

let passed = 0;
let failed = 0;

testCases.forEach((testCase, index) => {
  const result = normalizeSipUri(testCase.input);
  const success = result === testCase.expected;
  
  if (success) {
    passed++;
    console.log(`✅ Test ${index + 1}: PASSED`);
  } else {
    failed++;
    console.log(`❌ Test ${index + 1}: FAILED`);
  }
  
  console.log(`   Input:    ${testCase.input}`);
  console.log(`   Expected: ${testCase.expected}`);
  console.log(`   Got:      ${result}`);
  console.log();
});

console.log('=' .repeat(80));
console.log(`\nResults: ${passed} passed, ${failed} failed`);

if (failed === 0) {
  console.log('✅ All tests passed!');
  process.exit(0);
} else {
  console.log('❌ Some tests failed');
  process.exit(1);
}