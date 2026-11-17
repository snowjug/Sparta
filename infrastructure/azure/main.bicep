// Sparta on Azure.
//
//   Log Analytics + Application Insights  -> modules/monitoring.bicep
//   Virtual network + private DNS         -> modules/network.bicep      (privateNetworking = true)
//   Key Vault (RBAC) + managed identity   -> modules/keyvault.bicep
//   PostgreSQL Flexible Server            -> modules/postgres.bicep
//   Azure Managed Redis                   -> modules/redis.bicep
//   Container Apps: api, web, migrate job -> modules/containerapps.bicep
//   Optional: ACS, Speech, alerts         -> modules/acs.bicep, modules/speech.bicep, modules/alerts.bicep
//
// Deploy into an existing resource group (see docs/DEPLOYMENT.md for the commands and the secrets flow):
//   az deployment group create -g <rg> -f infrastructure/azure/main.bicep -p infrastructure/azure/main.bicepparam
//
// STATUS: compiles and lints with the Bicep CLI. It has NOT been deployed (no Azure subscription was used to write it), so
// expect to fix property or quota issues on the first real deployment. See "What is not verified" in docs/DEPLOYMENT.md.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------------------------------------------------
// Naming and placement
// ---------------------------------------------------------------------------------------------------------------------

@description('Lowercase letters and digits, 3-8 characters. Prefix of every resource name (Key Vault names are limited to 24 characters).')
@minLength(3)
@maxLength(8)
param namePrefix string = 'sparta'

@description('Environment label added to resource names.')
@allowed([
  'dev'
  'test'
  'prod'
])
param environmentName string = 'prod'

@description('Azure region. It must offer every service you enable: Container Apps, PostgreSQL Flexible Server, Azure Managed Redis (SKU below), and the Speech voices you need (hi-IN, kn-IN, en-IN).')
param location string = resourceGroup().location

param tags object = {
  application: 'sparta'
  environment: environmentName
}

// ---------------------------------------------------------------------------------------------------------------------
// Images
// ---------------------------------------------------------------------------------------------------------------------

@description('API image, for example ghcr.io/<owner>/sparta-api:sha-<commit>. Built from services/api/Dockerfile with the azure and otlp extras.')
param apiImage string

@description('Web image, built from apps/web/Dockerfile. NEXT_PUBLIC_* values are baked in at build time: build it with this deployment\'s public API URL.')
param webImage string

@description('Registry host for private images. Leave empty for public images.')
param registryServer string = ''
param registryUsername string = ''

@secure()
param registryPassword string = ''

// ---------------------------------------------------------------------------------------------------------------------
// Secrets. Never put values in a parameter file: main.bicepparam reads them from environment variables.
// ---------------------------------------------------------------------------------------------------------------------

@secure()
@minLength(1)
@description('SPARTA_DATA_KEYS: comma-separated Fernet keys, newest first. Generate with `python -m sparta keygen`.')
param dataKeys string

@secure()
@minLength(1)
@description('SPARTA_PEPPER')
param pepper string

@secure()
@minLength(1)
@description('SPARTA_WEBHOOK_SECRET')
param webhookSecret string

@secure()
@minLength(12)
@description('PostgreSQL administrator password (at least 12 characters).')
param postgresAdminPassword string

@secure()
@description('Bring-your-own Azure AI Speech key (leave empty with deploySpeech = true).')
param speechKey string = ''

@secure()
@description('Azure OpenAI key (needs azureOpenAiEndpoint and azureOpenAiDeployment).')
param azureOpenAiKey string = ''

@secure()
@description('Bring-your-own ACS connection string (leave empty with deployAcs = true).')
param acsConnectionString string = ''

// ---------------------------------------------------------------------------------------------------------------------
// Network and data tier
// ---------------------------------------------------------------------------------------------------------------------

@description('true: virtual network, PostgreSQL and Redis without a public endpoint (recommended). false: public endpoints protected by TLS, passwords and (PostgreSQL) a firewall that admits Azure-hosted clients; cheaper and simpler, for test environments only.')
param privateNetworking bool = true

param vnetAddressPrefix string = '10.40.0.0/16'
param acaSubnetPrefix string = '10.40.0.0/23'
param postgresSubnetPrefix string = '10.40.2.0/24'
param endpointsSubnetPrefix string = '10.40.3.0/24'

@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresTier string = 'Burstable'
param postgresSku string = 'Standard_B1ms'
param postgresStorageGb int = 32
param postgresBackupRetentionDays int = 7
param postgresGeoRedundantBackup bool = false
param postgresHighAvailability bool = false

@description('Extra public IPv4 addresses allowed to reach PostgreSQL (public mode only).')
param postgresAllowedPublicIps array = []

param redisSku string = 'Balanced_B0'
param redisHighAvailability bool = true

@description('Public network access to Key Vault. Calls are always authenticated and RBAC-authorised.')
@allowed([
  'Enabled'
  'Disabled'
])
param keyVaultPublicNetworkAccess string = 'Enabled'
param keyVaultPurgeProtection bool = true

// ---------------------------------------------------------------------------------------------------------------------
// Container Apps sizing
// ---------------------------------------------------------------------------------------------------------------------

param apiCpu string = '0.5'
param apiMemory string = '1Gi'
param apiMinReplicas int = 1
param apiMaxReplicas int = 3
param webCpu string = '0.25'
param webMemory string = '0.5Gi'
param webMinReplicas int = 1
param webMaxReplicas int = 2

// ---------------------------------------------------------------------------------------------------------------------
// Sparta settings (docs/DEPLOYMENT.md lists what each one does)
// ---------------------------------------------------------------------------------------------------------------------

@description('SPARTA_OIDC_ISSUER, for example https://login.microsoftonline.com/<tenant-id>/v2.0')
@minLength(1)
param oidcIssuer string

@description('SPARTA_OIDC_AUDIENCE, for example api://sparta-api')
@minLength(1)
param oidcAudience string

param oidcJwksUrl string = ''

@description('Additional browser origins for SPARTA_CORS_ORIGINS, for example a custom domain: https://app.example.com')
param extraCorsOrigins array = []

@description('Additional host names for SPARTA_TRUSTED_HOSTS, for example a custom domain: api.example.com')
param extraTrustedHosts array = []

@description('Expose the Simulator Lab endpoints. Keep off in a production tenant that serves real calls.')
param simulatorEnabled bool = false

@allowed([
  'simulator'
  'azure'
  'other'
])
param telephonyProvider string = 'simulator'

@allowed([
  'simulator'
  'azure'
])
param sttProvider string = 'simulator'

@allowed([
  'simulator'
  'azure'
])
param ttsProvider string = 'simulator'

@allowed([
  'rules'
  'azure_openai'
])
param llmProvider string = 'rules'

param azureOpenAiEndpoint string = ''
param azureOpenAiDeployment string = ''
param speechRegion string = location
param acsResourceId string = ''
param entraTenantId string = ''
param eventGridAudience string = ''
param telephonyOwnerUserId string = ''
param forwardingNumber string = ''
param otlpEndpoint string = ''
param logLevel string = 'INFO'
param dailyCallCap int = 200
param maxActiveCalls int = 5

// ---------------------------------------------------------------------------------------------------------------------
// Optional resources
// ---------------------------------------------------------------------------------------------------------------------

@description('Create an Azure Communication Services resource and store its connection string in Key Vault. Read the constraints in modules/acs.bicep first.')
param deployAcs bool = false

@description('Where ACS stores data at rest (cannot be changed later).')
param acsDataLocation string = 'India'

@description('Create an Azure AI Speech resource and store its key in Key Vault.')
param deploySpeech bool = false

@description('Email address for alerts. Empty = no alert rules.')
param alertEmail string = ''

param logRetentionDays int = 30
param logDailyQuotaGb int = 1

// ---------------------------------------------------------------------------------------------------------------------
// Names (computed here so every module agrees on them)
// ---------------------------------------------------------------------------------------------------------------------

var suffix = take(uniqueString(resourceGroup().id), 6)
var baseName = '${namePrefix}-${environmentName}'

var names = {
  identity: 'id-${baseName}'
  vault: 'kv-${baseName}-${suffix}'
  logs: 'log-${baseName}'
  appInsights: 'appi-${baseName}'
  vnet: 'vnet-${baseName}'
  postgresDnsZone: '${baseName}.private.postgres.database.azure.com'
  postgres: 'psql-${baseName}-${suffix}'
  redis: 'redis-${baseName}-${suffix}'
  containerAppsEnvironment: 'cae-${baseName}'
  api: 'ca-api-${baseName}'
  web: 'ca-web-${baseName}'
  migrate: 'caj-migrate-${baseName}'
  acs: 'acs-${baseName}-${suffix}'
  speech: 'speech-${baseName}-${suffix}'
  actionGroup: 'ag-${baseName}'
}

// ---------------------------------------------------------------------------------------------------------------------
// Resources
// ---------------------------------------------------------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.identity
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    tags: tags
    workspaceName: names.logs
    appInsightsName: names.appInsights
    retentionInDays: logRetentionDays
    dailyQuotaGb: logDailyQuotaGb
  }
}

module network 'modules/network.bicep' = if (privateNetworking) {
  name: 'network'
  params: {
    location: location
    tags: tags
    vnetName: names.vnet
    vnetAddressPrefix: vnetAddressPrefix
    acaSubnetPrefix: acaSubnetPrefix
    postgresSubnetPrefix: postgresSubnetPrefix
    endpointsSubnetPrefix: endpointsSubnetPrefix
    postgresDnsZoneName: names.postgresDnsZone
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    tags: tags
    vaultName: names.vault
    identityPrincipalId: identity.properties.principalId
    publicNetworkAccess: keyVaultPublicNetworkAccess
    enablePurgeProtection: keyVaultPurgeProtection
    dataKeys: dataKeys
    pepper: pepper
    webhookSecret: webhookSecret
    azureOpenAiKey: azureOpenAiKey
    speechKey: deploySpeech ? '' : speechKey
    acsConnectionString: deployAcs ? '' : acsConnectionString
    registryPassword: registryPassword
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    tags: tags
    serverName: names.postgres
    vaultName: names.vault
    administratorPassword: postgresAdminPassword
    tier: postgresTier
    skuName: postgresSku
    storageSizeGb: postgresStorageGb
    backupRetentionDays: postgresBackupRetentionDays
    geoRedundantBackup: postgresGeoRedundantBackup
    highAvailability: postgresHighAvailability
    privateNetworking: privateNetworking
    delegatedSubnetId: privateNetworking ? network!.outputs.postgresSubnetId : ''
    privateDnsZoneId: privateNetworking ? network!.outputs.postgresDnsZoneId : ''
    allowedPublicIps: postgresAllowedPublicIps
  }
  dependsOn: [
    keyVault
  ]
}

module redis 'modules/redis.bicep' = {
  name: 'redis'
  params: {
    location: location
    tags: tags
    redisName: names.redis
    vaultName: names.vault
    skuName: redisSku
    highAvailability: redisHighAvailability
    privateNetworking: privateNetworking
    endpointsSubnetId: privateNetworking ? network!.outputs.endpointsSubnetId : ''
    privateDnsZoneId: privateNetworking ? network!.outputs.redisDnsZoneId : ''
  }
  dependsOn: [
    keyVault
  ]
}

module acs 'modules/acs.bicep' = if (deployAcs) {
  name: 'acs'
  params: {
    tags: tags
    acsName: names.acs
    vaultName: names.vault
    dataLocation: acsDataLocation
  }
  dependsOn: [
    keyVault
  ]
}

module speech 'modules/speech.bicep' = if (deploySpeech) {
  name: 'speech'
  params: {
    location: location
    tags: tags
    speechName: names.speech
    vaultName: names.vault
  }
  dependsOn: [
    keyVault
  ]
}

var hasSpeechKey = deploySpeech || !empty(speechKey)
var hasOpenAiKey = !empty(azureOpenAiKey)
var hasAcsConnectionString = deployAcs || !empty(acsConnectionString)

module containerApps 'modules/containerapps.bicep' = {
  name: 'containerapps'
  params: {
    location: location
    tags: tags
    environmentName: names.containerAppsEnvironment
    apiAppName: names.api
    webAppName: names.web
    migrationJobName: names.migrate
    workspaceName: monitoring.outputs.workspaceName
    infrastructureSubnetId: privateNetworking ? network!.outputs.acaSubnetId : ''
    identityId: identity.id
    vaultUri: keyVault.outputs.vaultUri
    apiImage: apiImage
    webImage: webImage
    registryServer: registryServer
    registryUsername: registryUsername
    hasRegistryPassword: !empty(registryPassword)
    apiCpu: apiCpu
    apiMemory: apiMemory
    apiMinReplicas: apiMinReplicas
    apiMaxReplicas: apiMaxReplicas
    webCpu: webCpu
    webMemory: webMemory
    webMinReplicas: webMinReplicas
    webMaxReplicas: webMaxReplicas
    oidcIssuer: oidcIssuer
    oidcAudience: oidcAudience
    oidcJwksUrl: oidcJwksUrl
    extraCorsOrigins: extraCorsOrigins
    extraTrustedHosts: extraTrustedHosts
    simulatorEnabled: simulatorEnabled
    telephonyProvider: telephonyProvider
    sttProvider: sttProvider
    ttsProvider: ttsProvider
    llmProvider: llmProvider
    hasSpeechKey: hasSpeechKey
    speechRegion: speechRegion
    hasOpenAiKey: hasOpenAiKey
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeployment: azureOpenAiDeployment
    hasAcsConnectionString: hasAcsConnectionString
    acsResourceId: deployAcs ? acs!.outputs.acsResourceId : acsResourceId
    entraTenantId: entraTenantId
    eventGridAudience: eventGridAudience
    telephonyOwnerUserId: telephonyOwnerUserId
    forwardingNumber: forwardingNumber
    otlpEndpoint: otlpEndpoint
    logLevel: logLevel
    dailyCallCap: dailyCallCap
    maxActiveCalls: maxActiveCalls
  }
  // The apps resolve Key Vault secrets written by these modules, so they must exist first (ACS is already an implicit
  // dependency through acs!.outputs above).
  dependsOn: [
    postgres
    redis
    speech
  ]
}

module alerts 'modules/alerts.bicep' = if (!empty(alertEmail)) {
  name: 'alerts'
  params: {
    tags: tags
    actionGroupName: names.actionGroup
    alertEmail: alertEmail
    apiAppId: containerApps.outputs.apiAppId
    postgresServerId: postgres.outputs.serverId
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// Outputs (no secrets)
// ---------------------------------------------------------------------------------------------------------------------

output resourceGroupName string = resourceGroup().name
output apiFqdn string = containerApps.outputs.apiFqdn
output apiUrl string = 'https://${containerApps.outputs.apiFqdn}'
output webFqdn string = containerApps.outputs.webFqdn
output webUrl string = 'https://${containerApps.outputs.webFqdn}'
output apiAppName string = containerApps.outputs.apiAppName
output webAppName string = containerApps.outputs.webAppName
output migrationJobName string = containerApps.outputs.migrationJobName
output containerAppsDefaultDomain string = containerApps.outputs.environmentDefaultDomain
output keyVaultName string = keyVault.outputs.vaultName
output keyVaultUri string = keyVault.outputs.vaultUri
output logAnalyticsWorkspaceName string = monitoring.outputs.workspaceName
output postgresServerName string = postgres.outputs.serverName
output redisName string = redis.outputs.redisName
output identityName string = identity.name
output acsResourceIdOut string = deployAcs ? acs!.outputs.acsResourceId : acsResourceId
