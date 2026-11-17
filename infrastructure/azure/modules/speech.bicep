// Optional: an Azure AI Speech resource (speech-to-text and text-to-speech). Deploy it with deploySpeech = true; its key is
// written to Key Vault as "sparta-speech-key" without anyone handling it. en-IN, hi-IN and kn-IN are supported for
// recognition and synthesis (docs/research/azure-speech-openai-verification.md).
//
// Personal Voice is NOT enabled by this module: it needs Microsoft Limited Access approval, and it is not offered in the
// Central India region (docs/DEPLOYMENT.md, legal and approvals checklist).

param location string
param tags object
param speechName string
param vaultName string

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}

resource speech 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: speechName
  location: location
  tags: tags
  kind: 'SpeechServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: speechName
    publicNetworkAccess: 'Enabled'
    // The Speech adapters authenticate with a key, so local (key) authentication has to stay enabled.
    disableLocalAuth: false
  }
}

resource speechKeySecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-speech-key'
  properties: {
    value: speech.listKeys().key1
    contentType: 'Azure AI Speech key for SPARTA_AZURE_SPEECH_KEY'
  }
}

output speechName string = speech.name
output speechEndpoint string = speech.properties.endpoint
output speechRegion string = location
