// Optional: an Azure Communication Services resource (Call Automation lives here). Deploy it with deployAcs = true.
//
// Read before enabling (docs/research/acs-android-verification.md, docs/DEPLOYMENT.md):
//  * ACS cannot provision India (+91) phone numbers directly. For an Indian owner the realistic paths are Teams Phone
//    Extensibility / Operator Connect through a licensed carrier, or an Indian programmable-voice provider.
//  * ACS standalone telephony is scheduled to retire on 2028-09-30, and tenants without an ACS resource created before
//    2026-10-23 cannot acquire numbers for the retiring PSTN workloads.
//  * Nothing in Sparta has been exercised against a live ACS resource. This module only creates the resource and stores
//    its connection string in Key Vault (secret "sparta-acs-connection-string"). Phone numbers, the Event Grid
//    subscription for IncomingCall and the Entra app role are manual steps.

param tags object
param acsName string
param vaultName string

@description('Where ACS stores its data at rest: for example India, Europe, United States, UK. It cannot be changed later.')
param dataLocation string = 'India'

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: acsName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: dataLocation
  }
}

resource connectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-acs-connection-string'
  properties: {
    value: acs.listKeys().primaryConnectionString
    contentType: 'ACS connection string for SPARTA_ACS_CONNECTION_STRING'
  }
}

output acsName string = acs.name
output acsResourceId string = acs.id
output acsHostName string = acs.properties.hostName
