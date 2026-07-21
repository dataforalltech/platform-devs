# Rollback

A migration inicial é forward-only. O rollback de aplicação deve usar a imagem anterior, que permanece compatível com as colunas aditivas. Não remova tabelas/colunas durante rollback. Se o job falhar, interrompa a promoção antes do rollout; investigue o tenant informado e reexecute o job idempotente após correção. Remoção futura exige migration contract separada, backup e aprovação do owner.
