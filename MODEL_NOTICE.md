# English–Arabic model provenance

Veyora's offline translator adapter is original project code using CTranslate2 and SentencePiece. It downloads the existing Argos English→Arabic 1.0 model rather than embedding model weights in this source package.

Official package index:
https://github.com/argosopentech/argospm-index/blob/main/index.json

Model:
https://data.argosopentech.com/argospm/v1/translate-en_ar-1_0.argosmodel

Alternate model host listed in the official index:
https://argos-net.com/v1/translate-en_ar-1_0.argosmodel

Pinned SHA-256:
e2a6e84337f7ebbb55f9dc61dcba3a861c0d786ae5a46fa198fd8d6473f5c775

The package identifies source English and target Arabic, version 1.0. Its README attributes training data to OpenSubtitles and UNPC corpora compiled by OPUS. The archive also contains Stanza resources, which this adapter does not extract or use. Only model data, vocabulary, SentencePiece tokenizer, metadata and README are extracted.

The bundled model README does not provide a complete standalone commercial distribution license statement. Do not infer one from the Argos application or index license. Review upstream model/data and native dependency terms before distributing weights commercially. Original README metadata is preserved beside the downloaded model.

## Arabic→English added in 1.4

Official reverse model, version 1.0:
https://data.argosopentech.com/argospm/v1/translate-ar_en-1_0.argosmodel

Alternate official index link:
https://argos-net.com/v1/translate-ar_en-1_0.argosmodel

Archive size: 81,869,670 bytes.
Pinned SHA-256: bc98cd4e27ca1cebfae9b7086b2ebc635e4dbed45e7cb5f0891cb7d22feacfad

The reverse package metadata identifies Arabic source and English target. The same model-license and training-data provenance limitations noted above apply; no broader redistribution license is inferred.

## 2.0 review additions

The existing model catalog also contains English↔Turkish and English↔Korean (including configured package URLs/prefixes). All six direct model packages were downloaded and hash-verified during this session, and all twelve text routes ran. That establishes integrity/inference for those packages, not redistribution rights or linguistic quality. The installed README/metadata must be reviewed for each pair before commercial redistribution. Weights are excluded from the source ZIP.

Whisper `base` was downloaded for actual synthetic audio recognition tests. Arabic produced no recognized speech; Turkish and Korean contained substantial recognition errors. Do not represent those tests as full language accuracy validation. Larger selectable speech models were not quality-tested in this session.
