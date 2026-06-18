OPENQASM 3.0;
include "stdgates.inc";
qubit[3] q;
cry(pi/10) q[0], q[1];
cry(pi/10) q[2], q[1];
