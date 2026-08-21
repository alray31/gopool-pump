# GoPool Variable Speed Pump — custom_component (prototype, non testé en direct)

Intégration HACS dédiée pour la pompe GoPool AG1/IG1/IG2, en remplacement de
la configuration manuelle via localtuya + template YAML. Entités créées
automatiquement (dérivées de `const.py::DP_MAP`, seulement les DP confirmés
fonctionnels localement — voir le README principal du projet).

## ⚠️ Statut

Ce code a été écrit et vérifié syntaxiquement (compilation Python + JSON),
mais **n'a pas encore été testé contre une vraie pompe ni un vrai compte
Tuya** — je n'ai pas d'accès direct à Home Assistant ni à l'app Smart Life
depuis cet environnement. Traite ceci comme un point de départ solide à
valider chez toi, pas comme un produit fini.

Points les plus susceptibles de nécessiter un ajustement:
- Le nom exact de l'attribut IP sur l'objet `device` retourné par
  `tuya_sharing.Manager` (`pick_device` suppose `device.ip` — si ce n'est
  pas le bon nom, il retombera simplement sur `ip_override`, donc le flux
  reste utilisable même si cette hypothèse est fausse).
- L'interface exacte de `SharingTokenListener` (une seule méthode
  `update_token` est implémentée, en no-op, ce qui devrait suffire pour un
  flux one-shot).
- Le comportement de `tinytuya.set_socket_persistent(True)` avec un polling
  aux 15 secondes sur la durée — à surveiller pour la stabilité.

## Installation (test privé)

1. Copie `custom_components/gopool_pump/` dans `<config>/custom_components/`.
2. Redémarre Home Assistant.
3. Réglages → Appareils et services → Ajouter une intégration →
   "GoPool Variable Speed Pump".
4. Choisis "Saisie manuelle" pour un premier test garanti de fonctionner
   (mêmes device_id/local_key/IP que ta config localtuya actuelle), ou
   "Automatique" pour tester le flux QR.

## Path "Automatique" (QR)

Réutilise le mécanisme officiel `tuya-device-sharing-sdk` (le même que
l'intégration Tuya native de Home Assistant pour son propre login QR),
avec l'identifiant client public `HA_3y9q4ak7g4ephrvke` / schema
`haauthorize` que Tuya a délivré à Home Assistant — pas un secret propre à
ce projet. Ça fonctionne aujourd'hui selon les retours de la communauté
(voir `vineetchoudhary/tuya-local-key`), mais rien ne garantit que Tuya ne
limitera pas cet usage tiers un jour. La saisie manuelle reste toujours
disponible en secours, sans aucune dépendance à ce mécanisme.

Après connexion et scan du QR, l'app te fera choisir parmi tes appareils
liés — sélectionne ta pompe, confirme (ou corrige) son IP locale, et
l'intégration bascule immédiatement en 100% local (aucun autre appel cloud
par la suite).
