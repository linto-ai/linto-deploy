Si probleme de serveur, injouagnable en ssh, il faut passer par patrick Perera pour redémarer la machine (normalement ca redémare automatiquement)
-> Si une machine ne monte pas au niveau ssh ou kubernet a des probleme avec les pod, probleme côté OVH ?

- linto-deploy,-

Sur quadrant, les images sont piné, mais si changement de version (même mineur), il faut relancer un script a partir des source de vériter de la base de mongo

profile kube.linto-ai -> 1 vllm pour voxtral , 1 pour genma, 1 pour transcriptor,
mps sur la carte l40s (les deux process / images vllm tourne comme un seul process pour nvidia avec des tunning mémoire 048 voxtral et 052 pour translate genma)

Si un process vllm merde il devrais etre replanifier / redémarer
