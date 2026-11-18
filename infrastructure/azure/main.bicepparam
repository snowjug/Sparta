using './main.bicep'

// Example parameters for a production-style deployment. NOTHING SECRET LIVES IN THIS FILE.
// Secrets, image references and tenant-specific values are read from environment variables when the Bicep CLI builds the
// parameters, which is how .github/workflows/deploy.yml supplies them from GitHub environment secrets and how you supply
// them locally (docs/DEPLOYMENT.md). A required value that is missing is rejected by `az deployment group validate`
// before anything is created.
//
//   bash:        export SPARTA_DATA_KEYS=... ; az deployment group validate -g <rg> -f main.bicep -p main.bicepparam
//   PowerShell:  $env:SPARTA_DATA_KEYS = '...' ; az deployment group validate -g <rg> -f main.bicep -p main.bicepparam

// ---- naming and placement ----
param namePrefix = 'sparta'
param environmentName = readEnvironmentVariable('SPARTA_ENVIRONMENT_NAME', 'prod')
// param location = 'centralindia'   // default: the resource group's region; check Speech voices, ACS and Managed Redis availability

// ---- images (the deploy workflow sets both to the sha-<commit> tags it just published) ----
param apiImage = readEnvironmentVariable('SPARTA_API_IMAGE', 'ghcr.io/snowjug/sparta-api:latest')
param webImage = readEnvironmentVariable('SPARTA_WEB_IMAGE', 'ghcr.io/snowjug/sparta-web:latest')
// A private registry needs credentials (the password is stored in Key Vault):
// param registryServer = 'ghcr.io'
// param registryUsername = '<user>'
// param registryPassword = readEnvironmentVariable('REGISTRY_PASSWORD', '')

// ---- secrets: environment variables only ----
param dataKeys = readEnvironmentVariable('SPARTA_DATA_KEYS', '')
param pepper = readEnvironmentVariable('SPARTA_PEPPER', '')
param webhookSecret = readEnvironmentVariable('SPARTA_WEBHOOK_SECRET', '')
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD', '')
param speechKey = readEnvironmentVariable('AZURE_SPEECH_KEY', '')
param azureOpenAiKey = readEnvironmentVariable('AZURE_OPENAI_KEY', '')
param twilioAuthToken = readEnvironmentVariable('SPARTA_TWILIO_AUTH_TOKEN', '')

// ---- authentication (required: production accepts OIDC bearer tokens only) ----
param oidcIssuer = readEnvironmentVariable('SPARTA_OIDC_ISSUER', '')
param oidcAudience = readEnvironmentVariable('SPARTA_OIDC_AUDIENCE', '')

// ---- network and data tier ----
param privateNetworking = true      // false only for a throwaway test environment (public PostgreSQL and Redis endpoints)
param postgresTier = 'Burstable'
param postgresSku = 'Standard_B1ms'
param postgresStorageGb = 32
param postgresHighAvailability = false
param redisSku = 'Balanced_B0'

// ---- Container Apps ----
param apiMinReplicas = 1
param apiMaxReplicas = 3
param simulatorEnabled = false

// ---- providers: everything runs on the simulator until you switch it ----
param telephonyProvider = 'simulator'
param sttProvider = 'simulator'
param ttsProvider = 'simulator'
param llmProvider = 'rules'
// Real speech and language models (needs deploySpeech = true or AZURE_SPEECH_KEY, and for the model an Azure OpenAI
// resource that you create yourself, because model versions retire on a schedule):
// param deploySpeech = true
// param sttProvider = 'azure'
// param ttsProvider = 'azure'
// param llmProvider = 'azure_openai'
// param azureOpenAiEndpoint = 'https://<resource>.openai.azure.com'
// param azureOpenAiDeployment = '<deployment name>'
// Telephony through ACS: read modules/acs.bicep and docs/DEPLOYMENT.md first (no +91 numbers, retirement dates, nothing
// has been run against a live ACS resource).
// param deployAcs = true
// param telephonyProvider = 'azure'
// param eventGridAllowedAppIds = '<application id of the Microsoft.EventGrid service principal in your tenant>'   // required with telephonyProvider = 'azure'
// Telephony through Twilio (the number and the account are yours to create, docs/TELEPHONY.md; a TRIAL account removes
// <Stream> and <Dial><Number> from TwiML, so the account must be upgraded). SPARTA_TWILIO_AUTH_TOKEN comes from the
// environment above; point the number's voice webhook (HTTP POST) at https://<apiFqdn>/api/v1/webhooks/twilio/voice.
// param telephonyProvider = 'twilio'
// param twilioAccountSid = 'AC...'
// param twilioCallerId = '+1...'     // optional: the number shown on a takeover call (default: the number that was dialled)
// param telephonyOwnerUserId = '<the owner id real calls are delivered to>'
// param forwardingNumber = '+1...'   // the Twilio number callers dial (the doctor checks it on the account)

// ---- cost brakes (real calls only; simulated calls are never counted) ----
// param dailyCallCap = 200
// param dailyCallMinutesCap = 240    // minutes of real calls per owner per UTC day, 0 = off
// param perNumberDailyCallCap = 10   // real calls from one caller number per day, 0 = off
// param costCenter = '<budget or project code>'

// ---- custom domains: add them here after you create the DNS records and managed certificates ----
// param extraCorsOrigins = [ 'https://app.example.com' ]
// param extraTrustedHosts = [ 'api.example.com' ]

// ---- alerts ----
// param alertEmail = 'oncall@example.com'
