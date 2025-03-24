#  vercel tests
curl -X POST http://localhost:3000/api/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings": [{\n    "phoneNumber": "+17868748498"\n  }]\n}'

curl -X POST http://localhost:3000/api/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings": [{\n    "phoneNumber": "+17868748498", "callerId":"15aad0ec-4d50-4c7f-aa0d-2158316deb03"\n  }]\n}'

curl -X POST http://localhost:8000/api/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings": [{\n    "sipUri": "sip:+17868748498@daily-twilio-integration.sip.twilio.com"\n  }]\n}'



# Python Tests

curl -X POST http://localhost:8000/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings": [{\n    "phoneNumber": "+17868748498"\n  }], "voicemail_detection" :true\n}'

curl -X POST http://localhost:8000/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings":[{ "phoneNumber": "+17868748498"\n}], "voicemail_detection":{"testInPrebuilt":true}\n}'


curl -X POST http://localhost:8000/dial \\n-H "Content-Type: application/json" \\n-d '{\n  "dialout_settings": [{\n    "sipUri": "sip:+17868748498@daily-twilio-integration.sip.twilio.com"\n  }]\n}'