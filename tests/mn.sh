# script to simplify multi-node debugging
git add -A && git commit -m 'i' && git push --set-upstream origin $1
SHA=$(git rev-parse HEAD)
echo $SHA
kubectl delete  ElasticJob debugging -n elastic-job
cat mn.yaml | sed 's/%(SHA)s/$SHA/g' | kubectl create -f -
