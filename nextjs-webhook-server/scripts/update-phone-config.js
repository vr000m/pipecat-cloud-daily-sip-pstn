#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const axios = require('axios');

// Load environment variables
require('dotenv').config({ path: path.join(__dirname, '..', '.env.local') });

/**
 * Fetch phone numbers from Daily API (dialin config)
 * @param {string} apiKey - The API key for authentication
 * @param {string} apiUrl - The API URL (prod or staging)
 * @returns {Promise<Array>} - Array of phone configurations
 */
async function fetchPhoneNumbers(apiKey, apiUrl) {
  if (!apiKey) {
    console.log(`No API key provided for ${apiUrl}, skipping...`);
    return [];
  }

  try {
    console.log(`Fetching dialin config from ${apiUrl}...`);
    const response = await axios.get(`${apiUrl}/v1/domain-dialin-config`, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    });

    if (response.data && response.data.data) {
      console.log(`Found ${response.data.data.length} dialin configs from ${apiUrl}`);
      return response.data.data;
    }
    return [];
  } catch (error) {
    console.error(`Error fetching dialin config from ${apiUrl}:`, error.message);
    if (error.response) {
      console.error('Response status:', error.response.status);
      console.error('Response data:', error.response.data);
    }
    return [];
  }
}

/**
 * Fetch purchased phone numbers from Daily API
 * @param {string} apiKey - The API key for authentication
 * @param {string} apiUrl - The API URL (prod or staging)
 * @returns {Promise<Array>} - Array of purchased phone numbers
 */
async function fetchPurchasedPhoneNumbers(apiKey, apiUrl) {
  if (!apiKey) {
    console.log(`No API key provided for ${apiUrl}, skipping purchased phone numbers...`);
    return [];
  }

  try {
    console.log(`Fetching purchased phone numbers from ${apiUrl}...`);
    const response = await axios.get(`${apiUrl}/v1/purchased-phone-numbers`, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    });

    if (response.data && response.data.data) {
      console.log(`Found ${response.data.data.length} purchased phone numbers from ${apiUrl}`);
      return response.data.data;
    }
    return [];
  } catch (error) {
    console.error(`Error fetching purchased phone numbers from ${apiUrl}:`, error.message);
    if (error.response) {
      console.error('Response status:', error.response.status);
      console.error('Response data:', error.response.data);
    }
    return [];
  }
}

/**
 * Transform Daily API response to our phone.yml format
 * @param {Array} dailyPhones - Array of phone configs from Daily API (dialin config)
 * @param {Array} purchasedPhones - Array of purchased phone numbers from Daily API
 * @returns {Array} - Transformed phone configurations
 */
function transformPhoneData(dailyPhones, purchasedPhones = []) {
  // Debug log the first phone object to see structure
  if (dailyPhones.length > 0) {
    console.log('Sample dialin config structure:', JSON.stringify(dailyPhones[0], null, 2));
  }
  if (purchasedPhones.length > 0) {
    console.log('Sample purchased phone structure:', JSON.stringify(purchasedPhones[0], null, 2));
  }

  // Create a lookup map for purchased phone numbers by number
  const purchasedLookup = {};
  purchasedPhones.forEach(purchased => {
    if (purchased.number) {
      purchasedLookup[purchased.number] = purchased.id;
    }
  });

  return dailyPhones
    .filter(phone => {
      // Check for phone number in the config object
      const hasPhoneNumber = phone.config?.phone_number;
      if (!hasPhoneNumber) {
        console.log(`Skipping entry ${phone.id} - no phone number found`);
      }
      return hasPhoneNumber;
    })
    .map(phone => {
      const phoneNumber = phone.config.phone_number;
      const purchasedPhoneId = purchasedLookup[phoneNumber];
      
      if (!purchasedPhoneId) {
        console.log(`Warning: No purchased phone ID found for ${phoneNumber}`);
      }
      
      return {
        id: phone.id, // dialin config ID
        purchased_phone_id: purchasedPhoneId || null, // purchased phone number ID for callerId
        number: phoneNumber,
        description: phone.config.name_prefix || phone.config.name || 'Phone number from Daily',
        webhook_url: phone.config.room_creation_api || null,
        sip_uri: phone.config.sip_uri || null,
        hmac_secret: phone.config.hmac || null,
        type: phone.type || null
      };
    });
}

/**
 * Update the phone.yml file with fetched data
 */
async function updatePhoneConfig() {
  const configPath = path.join(__dirname, '..', 'phone.yml');
  
  // Fetch from both environments
  const prodApiKey = process.env.DAILY_API_KEY_PROD || process.env.PIPECAT_CLOUD_API_KEY_PROD;
  const stagingApiKey = process.env.DAILY_API_KEY_STAGING || process.env.PIPECAT_CLOUD_API_KEY_STAGING;

  // Fetch dialin configs
  const prodPhones = await fetchPhoneNumbers(prodApiKey, 'https://api.daily.co');
  const stagingPhones = await fetchPhoneNumbers(stagingApiKey, 'https://api.staging.daily.co');

  // Fetch purchased phone numbers
  const prodPurchasedPhones = await fetchPurchasedPhoneNumbers(prodApiKey, 'https://api.daily.co');
  const stagingPurchasedPhones = await fetchPurchasedPhoneNumbers(stagingApiKey, 'https://api.staging.daily.co');

  // Transform the data by merging dialin configs with purchased phone IDs
  const phoneConfig = {
    '# Phone number to environment mapping': null,
    '# This file maps phone numbers to their respective environments (prod/staging)': null,
    '# The webhook server uses this to dynamically route calls to the correct environment': null,
    '# Auto-generated by scripts/update-phone-config.js': null,
    '# Last updated': new Date().toISOString(),
    '': null,
    prod: {
      phone_numbers: transformPhoneData(prodPhones, prodPurchasedPhones)
    },
    staging: {
      phone_numbers: transformPhoneData(stagingPhones, stagingPurchasedPhones)
    }
  };

  // Handle empty arrays gracefully
  if (phoneConfig.prod.phone_numbers.length === 0) {
    console.log('No production phone numbers found');
    phoneConfig.prod.phone_numbers = [
      {
        id: 'placeholder',
        number: '+10000000000',
        description: 'Add your production phone numbers here'
      }
    ];
  }

  if (phoneConfig.staging.phone_numbers.length === 0) {
    console.log('No staging phone numbers found');
    phoneConfig.staging.phone_numbers = [
      {
        id: 'placeholder',
        number: '+10000000001',
        description: 'Add your staging phone numbers here'
      }
    ];
  }

  // Write the updated config
  try {
    // Convert to YAML, handling comments specially
    let yamlContent = '# Phone number to environment mapping\n';
    yamlContent += '# This file maps phone numbers to their respective environments (prod/staging)\n';
    yamlContent += '# The webhook server uses this to dynamically route calls to the correct environment\n';
    yamlContent += '# Auto-generated by scripts/update-phone-config.js\n';
    yamlContent += `# Last updated: ${new Date().toISOString()}\n\n`;
    
    const configWithoutComments = {
      prod: phoneConfig.prod,
      staging: phoneConfig.staging
    };
    
    yamlContent += yaml.dump(configWithoutComments, {
      indent: 2,
      lineWidth: -1,
      quotingType: '"',
      forceQuotes: false
    });

    fs.writeFileSync(configPath, yamlContent);
    console.log(`✅ Successfully updated ${configPath}`);
    
    // Print summary
    console.log('\nSummary:');
    console.log(`- Production numbers: ${phoneConfig.prod.phone_numbers.filter(p => p.id !== 'placeholder').length}`);
    console.log(`- Staging numbers: ${phoneConfig.staging.phone_numbers.filter(p => p.id !== 'placeholder').length}`);
    
    // Print the actual numbers for verification
    console.log('\nProduction numbers:');
    phoneConfig.prod.phone_numbers
      .filter(p => p.id !== 'placeholder')
      .forEach(p => console.log(`  - ${p.number} (${p.description})`));
    
    console.log('\nStaging numbers:');
    phoneConfig.staging.phone_numbers
      .filter(p => p.id !== 'placeholder')
      .forEach(p => console.log(`  - ${p.number} (${p.description})`));
    
  } catch (error) {
    console.error('Error writing phone.yml:', error);
    process.exit(1);
  }
}

// Run the update if this script is executed directly
if (require.main === module) {
  console.log('🔄 Updating phone configuration from Daily APIs...\n');
  updatePhoneConfig().catch(error => {
    console.error('Failed to update phone config:', error);
    process.exit(1);
  });
}

module.exports = { updatePhoneConfig, fetchPhoneNumbers, fetchPurchasedPhoneNumbers, transformPhoneData };