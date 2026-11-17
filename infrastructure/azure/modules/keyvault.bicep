// Key Vault with Azure RBAC (no access policies), soft delete and purge protection. It holds every secret the API reads at
// runtime. Container Apps resolves them with the user-assigned managed identity, which gets only "Key Vault Secrets User"
// (read secret values) on this one vault. Secrets owned by other modules (database URL, Redis URL, ACS, Speech) are
// written by those modules so no secret ever travels through a template output.

param location string
param tags object
param vaultName string

@description('Principal (object) id of the user-assigned identity that reads the secrets.')
param identityPrincipalId string

@description('Public network access to the vault. Every call is still authenticated with Microsoft Entra ID and authorised by RBAC; see docs/DEPLOYMENT.md for the private-endpoint trade-off.')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

@description('Purge protection cannot be switched off once on, and it blocks re-using the vault name for the retention period. Turn it off only for throwaway environments.')
param enablePurgeProtection bool = true

param softDeleteRetentionInDays int = 90

@secure()
@description('Comma-separated Fernet keys; the first encrypts, all decrypt (rotation). Generate with: python -m sparta keygen')
param dataKeys string

@secure()
param pepper string

@secure()
param webhookSecret string

@secure()
param azureOpenAiKey string = ''

@secure()
@description('Bring-your-own Azure AI Speech key. Leave empty when the template creates the Speech resource (it writes its own key).')
param speechKey string = ''

@secure()
@description('Bring-your-own ACS connection string. Leave empty when the template creates the ACS resource (it writes its own).')
param acsConnectionString string = ''

@secure()
param registryPassword string = ''

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: publicNetworkAccess
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identityPrincipalId, keyVaultSecretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource dataKeysSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-data-keys'
  properties: {
    value: dataKeys
    contentType: 'Comma-separated Fernet keys; the first encrypts, all decrypt'
  }
}

resource pepperSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-pepper'
  properties: {
    value: pepper
    contentType: 'HMAC pepper for caller-number fingerprints'
  }
}

resource webhookSecretResource 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-webhook-secret'
  properties: {
    value: webhookSecret
    contentType: 'Webhook HMAC secret'
  }
}

resource openAiKeySecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (!empty(azureOpenAiKey)) {
  parent: vault
  name: 'sparta-openai-key'
  properties: {
    value: azureOpenAiKey
    contentType: 'Azure OpenAI key'
  }
}

resource registryPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (!empty(registryPassword)) {
  parent: vault
  name: 'sparta-registry-password'
  properties: {
    value: registryPassword
    contentType: 'Container registry password'
  }
}

resource speechKeySecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (!empty(speechKey)) {
  parent: vault
  name: 'sparta-speech-key'
  properties: {
    value: speechKey
    contentType: 'Azure AI Speech key for SPARTA_AZURE_SPEECH_KEY'
  }
}

resource acsConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (!empty(acsConnectionString)) {
  parent: vault
  name: 'sparta-acs-connection-string'
  properties: {
    value: acsConnectionString
    contentType: 'ACS connection string for SPARTA_ACS_CONNECTION_STRING'
  }
}

output vaultName string = vault.name
output vaultUri string = vault.properties.vaultUri
output vaultId string = vault.id
output roleAssignmentId string = secretsUser.id
