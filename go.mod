module eng.vyatta.net/protocols-frr

go 1.21

require (
	eng.vyatta.net/protocols v0.0.0
	github.com/Sirupsen/logrus v1.0.6
	github.com/danos/encoding v0.0.0
	github.com/hashicorp/go-multierror v1.1.1
)

require github.com/hashicorp/errwrap v1.0.0 // indirect

replace eng.vyatta.net/protocols => github.com/danos/golang-github-danos-protocols v0.0.0-20210520134247-5f17dbdcfda3

replace github.com/danos/encoding => github.com/danos/encoding v0.0.0-20210510150742-b4b9f2e26c28
