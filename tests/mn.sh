git add -A && git commit -m 'i' && git push origin $1
SHA=$(git rev-parse HEAD)
echo $SHA
